import random
import ssl
import websockets
import asyncio
import threading
import os
import sys
import json
import argparse
import time
from io import BytesIO
import cv2
import numpy
import sys
import mp as pn
detector = pn.Model()

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject, GLib
gi.require_version('GstWebRTC', '1.0')
from gi.repository import GstWebRTC
gi.require_version('GstSdp', '1.0')
from gi.repository import GstSdp
gi.require_version('GstApp', '1.0')


from websockets.version import version as wsv
#GObject.threads_init()


# Main pipeline here:
PIPELINE_DESC2 = '''
webrtcbin name=sendrecv bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
 videotestsrc is-live=true pattern=ball ! videoconvert ! queue ! vp8enc deadline=1 ! rtpvp8pay !
 queue ! application/x-rtp,media=video,encoding-name=VP8,payload=97 ! sendrecv.
'''

image_arr = None
sender = None
pipetmp = None
caps_global = None


class WebRTCClient:


    def __init__(self, id_, peer_id, server):
        self.id_ = id_
        self.conn = None
        # self.conn_meta = None
        self.pipe = None
        self.pipe2 = None
        self.webrtc = None
        self.peer_id = peer_id
        self.stun_server = "stun://stun.l.google.com:19302"
        self.server = server or 'wss://dxmpp.online:8443'
        # self.server_meta = 'wss://dxmpp.online:8000'

        self.is_push_buffer_allowed = False
        self._mainloop = GLib.MainLoop()
        self._src = None
        self.image_arr = numpy.zeros((480,640,3), numpy.uint8)

        # Framerate control attributes:
        self.done_processing = True
        self.interval_ms = 33
        self.frame_stamp = 0
        self.thread_1 = None
        self.arr = None

    def gst_to_opencv(self, sample):
        buf = sample.get_buffer()
        buff=buf.extract_dup(0, buf.get_size())
        global caps_global
        caps = sample.get_caps()
        caps_global = caps
        
        #print(caps.get_structure(0).get_value('format'))
        #print(caps.get_structure(0).get_value('height'))
        #print(caps.get_structure(0).get_value('width'))
        # print(buf.get_size())
    
        arr = numpy.ndarray((caps.get_structure(0).get_value('height'), caps.get_structure(0).get_value('width'), 3), buffer=buff, dtype=numpy.uint8)
        return arr

    def process_buffer(self):
        self.done_processing = False

        metadata, self.image_arr = detector.posenet_detect(self.arr)
        
        # Send metadata via Websocket connection
        msg = json.dumps({"keypoints": metadata})
        #msg = '{' + "'keypoints': " + f"{metadata}"  + '}'
        
        # Produce to Kafka topic
        #producer.send('pose_meta', key=b'keypoints', value=msg.encode('utf-8'))
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self.conn.send(msg))
            loop.close()
        except:
            print('Meta transmission error')

        self.done_processing = True
         
    
    def new_buffer(self, sink, data):
        time_now = 1000 * time.time()
        real_frame_interval = time_now - self.frame_stamp
        self.frame_stamp = time_now
        print("-----------------> Frametime: ", real_frame_interval)
        sample = sink.emit("pull-sample")
        if (self.done_processing is True): # and (real_frame_interval >= self.interval_ms)):
            self.arr = self.gst_to_opencv(sample)
            a = 1000 * time.time()
            self.arr = cv2.resize(self.arr, (640, 480), interpolation = cv2.INTER_NEAREST)
            self.arr = cv2.flip(self.arr, 1)
            threading.Thread(target=self.process_buffer).start()
            #self.image_arr = self.arr
            print("====> Time to process a frame: ", ((1000 * time.time()) - a))
        return Gst.FlowReturn.OK

    def start_feed(self, src, length):
        #print('======================> need data length: %s' % length)
        self.is_push_buffer_allowed = True
        #ret,thresh1 = cv2.threshold(image_arr,127,255,cv2.THRESH_BINARY)
        #metadata, self.image_arr = detector.posenet_detect(self.image_arr)
        self.push(self.image_arr)

    def stop_feed(self, src):
        #print('======================> enough_data')
        self.is_push_buffer_allowed = False
    
    def run(self):
        """ Run - blocking. """
        self._mainloop.run()
    
    def push(self, data):
        #print('Push a buffer into the source')
        
        if self.is_push_buffer_allowed:
            # print('Push allowed')
            data1 = data.tobytes()
            buf = Gst.Buffer.new_allocate(None, len(data1), None)
            buf.fill(0, data1)
            # Create GstSample
            sample = Gst.Sample.new(buf, Gst.caps_from_string("video/x-raw,format=BGR,width=640,height=480,framerate=(fraction)30/1"), None, None)
            # Push Sample on appsrc
            gst_flow_return = self._src.emit('push-sample', sample)

            if gst_flow_return != Gst.FlowReturn.OK:
                print('We got some error, stop sending data')

        else:
            pass
            #print('It is enough data for buffer....')
    

    async def connect(self):
        print('Connect stage!')
        sslctx = ssl.create_default_context(purpose=ssl.Purpose.CLIENT_AUTH)
        self.conn = await websockets.connect(self.server, ssl=sslctx)
        self.conn_meta = await websockets.connect(self.server_meta, ssl=sslctx)
        await self.conn.send('HELLO %d' % self.id_)
        await self.conn_meta.send('HELLO %d' % self.id_)

    async def setup_call(self):
        print('Setup call stage!')
        await self.conn.send('SESSION {}'.format(self.peer_id))

    def send_sdp_offer(self, offer):
        print('Send SDP offer stage!')
        text = offer.sdp.as_text()
        print ('Sending offer:\n%s' % text)
        msg = json.dumps({'sdp': {'type': 'offer', 'sdp': text}})
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.conn.send(msg))
        loop.close()

    def on_offer_created(self, promise, _, __):
        print('on_offer_created stage!')
        promise.wait()
        reply = promise.get_reply()
        offer = reply.get_value('offer')
        promise = Gst.Promise.new()
        self.webrtc.emit('set-local-description', offer, promise)
        promise.interrupt()
        self.send_sdp_offer(offer)

    def on_negotiation_needed(self, element):
        print('on_negotiation_needed stage!')
        promise = Gst.Promise.new_with_change_func(self.on_offer_created, element, None)
        element.emit('create-offer', None, promise)

    def send_ice_candidate_message(self, _, mlineindex, candidate):
        print('Send ice candidate stage!')
        icemsg = json.dumps({'ice': {'candidate': candidate, 'sdpMLineIndex': mlineindex}})
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.conn.send(icemsg))
        loop.close()

    def on_incoming_decodebin_stream(self, _, pad):
        print('On incoming decodebin stream stage!')
        if not pad.has_current_caps():
            print (pad, 'has no caps, ignoring')
            return

        # caps = pad.get_current_caps()
        caps = Gst.caps_from_string("video/x-raw, format=(string){BGR, GRAY8}; video/x-bayer,format=(string){rggb,bggr,grbg,gbrg},framerate=30/1")
        # print(caps.get_structure(0).get_value('format'))
        # print(caps.get_structure(0).get_value('height'))
        # print(caps.get_structure(0).get_value('width'))
        name = caps.to_string()
        if name.startswith('video'):
            q = Gst.ElementFactory.make('queue2')
            #capsfilter = Gst.ElementFactory.make('capsfilter')
            #capsfilter.set_property("caps", Gst.caps_from_string("video/x-raw,framerate=(fraction)30/1"))
            conv = Gst.ElementFactory.make('videoconvert')
            r = Gst.ElementFactory.make('videorate')
            #r.set_property("max-rate", 30)
            # sink = Gst.ElementFactory.make('autovideosink')
            sink = Gst.ElementFactory.make('appsink', 'sink')
            #q.set_property("max-size-bytes", 65586)
            sink.set_property("emit-signals", True)
            sink.set_property("enable-last-sample", False)
            sink.set_property("sync", False)
            sink.set_property("drop", True)
            sink.set_property("async", True)
            sink.set_property("max-buffers", 2)
            #sink.set_property("max-lateness", 66000000)
            sink.set_property("caps", caps)
            
            self.pipe.add(q)
            self.pipe.add(conv)
            #self.pipe.add(r)
            self.pipe.add(sink)
            self.pipe.sync_children_states()
            pad.link(q.get_static_pad('sink'))
            q.link(conv)
            #capsfilter.link(conv)
            #pad.link(r.get_static_pad('sink'))
            #r.link(conv)
            conv.link(sink)
            #r.link(sink)
            sink.connect("new-sample", self.new_buffer, sink)
            
        elif name.startswith('audio'):
            pass
            

    def on_incoming_stream(self, _, pad):
        print('On incoming stream stage!')
        if pad.direction != Gst.PadDirection.SRC:
            print('Pad Direction not source!')
            return

        decodebin = Gst.ElementFactory.make('decodebin')
        decodebin.connect('pad-added', self.on_incoming_decodebin_stream)
        #decodebin.set_property('use-buffering', False)
        #decodebin.set_property('max-size-buffers', 1)
        print('Called on incoming decodebin stream!')
        self.pipe.add(decodebin)
        decodebin.sync_state_with_parent()
        self.webrtc.link(decodebin)

    def start_pipeline(self):
        print('Starting pipeline!')
    
        #caps_src = Gst.caps_from_string("video/x-raw,format=BGR,width=640,height=480,framerate=(fraction)30/1")

        self.pipe = Gst.parse_launch(PIPELINE_DESC2)
        
        self.webrtc = self.pipe.get_by_name('sendrecv')
        self.webrtc.connect('on-negotiation-needed', self.on_negotiation_needed)
        self.webrtc.connect('on-ice-candidate', self.send_ice_candidate_message)
        self.webrtc.connect('pad-added', self.on_incoming_stream)
        
        self._src = self.pipe.get_by_name('source1')
        self._src.set_property('emit-signals', True)
        #self._src.set_property('leaky-type', 2)
        #self._src.set_property('max-bytes', 1000)
        self._src.set_property('max-bytes', 1000000)
        #self._src.set_property('caps', caps_src)
        self._src.set_property('format', 'time')
        self._src.set_property('do-timestamp', True)
        self._src.connect('need-data', self.start_feed)
        self._src.connect('enough-data', self.stop_feed)

        self.pipe.set_state(Gst.State.PLAYING)
        

    def handle_sdp(self, message):
        print('Handle sdp message stage!')
        #assert (self.webrtc)
        msg = json.loads(message)
        if 'sdp' in msg:
            sdp = msg['sdp']
            print(sdp['type'], sdp['sdp'])
            #assert(sdp['type'] == 'answer')
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
        try:
            self.pipe.set_state(Gst.State.NULL)
        except:
            pass
        self.pipe = None
        self.webrtc = None

    async def loop(self):
        assert self.conn
        async for message in self.conn:
            print(message)
            sdpoffer = "offer"
            if message == 'HELLO':
                pass
                #await self.setup_call()
            elif message == 'SESSION_OK':
            	print('SESSION OK!!!')
            	#self.start_pipeline()
            elif message.startswith('ERROR'):
                print (message)
                self.close_pipeline()
                return 1
            elif sdpoffer in message:
                print('SDP OFFER IN MESSAGE')
                self.start_pipeline()
                
            else:
                self.handle_sdp(message)
        self.close_pipeline()
        return 0

    async def stop(self):
        if self.conn:
            await self.conn.close()
            await self.conn_meta.close()
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
    while True:	
        Gst.init(None)
        if not check_plugins():
            sys.exit(1)
        parser = argparse.ArgumentParser()
        parser.add_argument('peerid', help='String ID of the peer to connect to')
        parser.add_argument('--server', help='Signalling server to connect to, eg "wss://127.0.0.1:8443"')
        args = parser.parse_args()
        our_id = 7331
        c = WebRTCClient(our_id, args.peerid, args.server)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(c.connect())
        res = loop.run_until_complete(c.loop())
        #sys.exit(res)