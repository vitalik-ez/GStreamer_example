import random
import ssl
import websockets
import asyncio
import os
import sys
import json
import argparse
import numpy as np

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
gi.require_version('GstWebRTC', '1.0')
from gi.repository import GstWebRTC
gi.require_version('GstSdp', '1.0')
from gi.repository import GstSdp

PIPELINE_DESC = '''
webrtcbin name=sendrecv latency=1 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302 
videotestsrc is-live=True ! 
videorate ! videoconvert ! video/x-raw,format=I420 !
x264enc ! video/x-h264,profile=baseline,bitrate=0,gop-size=-1,qos=True,preset=hp !
h264parse ! rtph264pay ! queue max-size-buffers=1 ! application/x-rtp,media=video,encoding-name=H264,payload=123 !
sendrecv.
'''

PIPELINE_DESC_WITHOUT_WEBRTC = '''
 appsrc name=source emit-signals=True is-live=True caps=video/x-raw,format=I420,width=640,height=480,framerate=10/1 ! 
 queue max-size-buffers=4 ! videoconvert ! autovideosink 
'''

start_pipeline = True
VIDEO_FORMAT = "RGB"
WIDTH, HEIGHT = 640, 480
FPS = '30/1'
DEFAULT_CAPS = f"video/x-raw,format=RGB,width={WIDTH},height={HEIGHT},framerate=10/1"

from websockets.version import version as wsv

image_arr = np.zeros((480, 640), np.uint8)

def ndarray_to_gst_buffer(array: np.ndarray) -> Gst.Buffer:
    """Converts numpy array to Gst.Buffer"""
    global image_arr
    return Gst.Buffer.new_wrapped(image_arr.tobytes())

def gst_to_opencv(sample):
    buf = sample.get_buffer()
    buff = buf.extract_dup(0, buf.get_size())

    caps = sample.get_caps().get_structure(0)
    w, h = caps.get_value('width'), caps.get_value('height')

    arr = np.ndarray(shape=(h, w),
                     buffer=buff,
                     dtype=np.uint8)

    return arr

def new_buffer(sink, data):
    global image_arr
    sample = sink.emit("pull-sample")
    arr = gst_to_opencv(sample)
    image_arr = arr
    return Gst.FlowReturn.OK

class WebRTCClient:
    def __init__(self, id_, peer_id, server):
        self.id_ = id_
        self.conn = None
        self.pipe = None
        self.webrtc = None
        self.peer_id = peer_id
        self.server = server or 'wss://webrtc.deepxhub.com:8443'


    async def connect(self):
        sslctx = ssl.create_default_context(purpose=ssl.Purpose.CLIENT_AUTH)
        self.conn = await websockets.connect(self.server, ssl=sslctx)
        await self.conn.send(f'HELLO {self.id_}')
        print('Connected')

    async def setup_call(self):
        await self.conn.send('SESSION {}'.format(self.peer_id))

    def send_sdp_offer(self, offer):
        text = offer.sdp.as_text()
        print ('Sending offer:\n%s' % text)
        msg = json.dumps({'sdp': {'type': 'offer', 'sdp': text}})
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.conn.send(msg))
        loop.close()

    def on_offer_created(self, promise, _, __):
        promise.wait()
        reply = promise.get_reply()
        offer = reply.get_value('offer')
        promise = Gst.Promise.new()
        self.webrtc.emit('set-local-description', offer, promise)
        promise.interrupt()
        self.send_sdp_offer(offer)

    def on_negotiation_needed(self, element):
        promise = Gst.Promise.new_with_change_func(self.on_offer_created, element, None)
        element.emit('create-offer', None, promise)

    def send_ice_candidate_message(self, _, mlineindex, candidate):
        icemsg = json.dumps({'ice': {'candidate': candidate, 'sdpMLineIndex': mlineindex, "sdpMid":"video0"}})
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.conn.send(icemsg))
        loop.close()

    def on_incoming_decodebin_stream(self, _, pad):
        if not pad.has_current_caps():
            print (pad, 'has no caps, ignoring')
            return
        

        '''
        caps = pad.get_current_caps()
        assert (len(caps))
        s = caps[0]
        name = s.get_name()
        '''

        caps = pad.get_current_caps()
        name = caps.to_string()
        
        if name.startswith('video'):
            q = Gst.ElementFactory.make('queue')
            conv = Gst.ElementFactory.make('videoconvert')

            sink = Gst.ElementFactory.make('appsink')
            sink.set_property('sync', False)
            #sink.set_property("emit-signals", True)
            #ssink.connect("new-sample", new_buffer, sink)

            q.set_property('leaky', 'downstream')
            self.pipe.add(q)
            self.pipe.add(conv)
            self.pipe.add(sink)
            self.pipe.sync_children_states()
            pad.link(q.get_static_pad('sink'))
            q.link(conv)
            conv.link(sink)
        elif name.startswith('audio'):
            pass
            '''
            q = Gst.ElementFactory.make('queue')
            conv = Gst.ElementFactory.make('audioconvert')
            resample = Gst.ElementFactory.make('audioresample')
            sink = Gst.ElementFactory.make('autoaudiosink')
            self.pipe.add(q)
            self.pipe.add(conv)
            self.pipe.add(resample)
            self.pipe.add(sink)
            self.pipe.sync_children_states()
            pad.link(q.get_static_pad('sink'))
            q.link(conv)
            conv.link(resample)
            resample.link(sink)
            '''

    def on_incoming_stream(self, _, pad):
        if pad.direction != Gst.PadDirection.SRC:
            return

        decodebin = Gst.ElementFactory.make('decodebin')
        decodebin.connect('pad-added', self.on_incoming_decodebin_stream)
        self.pipe.add(decodebin)
        decodebin.sync_state_with_parent()
        self.webrtc.link(decodebin)

    def start_pipeline(self):
        self.pipe = Gst.parse_launch(PIPELINE_DESC)
        
        self.webrtc = self.pipe.get_by_name('sendrecv')
        self.webrtc.connect('on-negotiation-needed', self.on_negotiation_needed)
        self.webrtc.connect('on-ice-candidate', self.send_ice_candidate_message)
        self.webrtc.connect('pad-added', self.on_incoming_stream)

        #appsrc = self.pipe.get_by_name('source')
        #appsrc.set_property("format", Gst.Format.TIME)   
        #appsrc.set_property("block", True)
        #appsrc.emit("push-buffer", ndarray_to_gst_buffer(image_arr))
        #appsrc.emit("end-of-stream")
        self.pipe.set_state(Gst.State.PLAYING)
        
        

    def handle_sdp(self, message):
        assert (self.webrtc)
        msg = json.loads(message)
        if 'sdp' in msg:
            sdp = msg['sdp']
            assert(sdp['type'] == 'answer')
            sdp = sdp['sdp']
            print ('Received answer:\n%s' % sdp)
            res, sdpmsg = GstSdp.SDPMessage.new()
            GstSdp.sdp_message_parse_buffer(bytes(sdp.encode()), sdpmsg)
            answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, sdpmsg)
            promise = Gst.Promise.new()
            self.webrtc.emit('set-remote-description', answer, promise)
            promise.interrupt()
        elif 'ice' in msg:
            ice = msg['ice']
            candidate = ice['candidate']
            sdpmlineindex = ice['sdpMLineIndex']
            self.webrtc.emit('add-ice-candidate', sdpmlineindex, candidate)

    def close_pipeline(self):
        self.pipe.set_state(Gst.State.NULL)
        self.pipe = None
        self.webrtc = None

    async def loop(self):
        assert self.conn
        async for message in self.conn:
            print(message)
            if message == 'HELLO':
                pass #await self.setup_call()
            elif message == 'SESSION_OK':
                pass #self.start_pipeline()
            elif message == 'CONNECT':
                self.start_pipeline()
            elif message.startswith('ERROR'):
                print (message)
                self.close_pipeline()
                return 1
            else:
                global start_pipeline
                if start_pipeline:
                    self.start_pipeline()
                    start_pipeline = False
                else:
                    self.handle_sdp(message)
        self.close_pipeline()
        return 0

    async def stop(self):
        if self.conn:
            await self.conn.close()
        self.conn = None


def check_plugins():
    needed = ["opus", "vpx", "nice", "webrtc", "dtls", "srtp", "rtp",
              "rtpmanager", "videotestsrc", "audiotestsrc"]
    missing = list(filter(lambda p: Gst.Registry.get().find_plugin(p) is None, needed))
    if len(missing):
        print('Missing gstreamer plugins:', missing)
        return False
    return True


if __name__=='__main__':
    Gst.init(None)
    if not check_plugins():
        sys.exit(1)
    parser = argparse.ArgumentParser()
    parser.add_argument('peerid', help='String ID of the peer to connect to')
    parser.add_argument('--server', help='Signalling server to connect to, eg "wss://127.0.0.1:8443"')
    args = parser.parse_args()
    our_id = random.randrange(10, 10000)
    #print(our_id)
    c = WebRTCClient(args.peerid, args.peerid, args.server)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(c.connect())
    res = loop.run_until_complete(c.loop())
    sys.exit(res)
