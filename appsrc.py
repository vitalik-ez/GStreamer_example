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


PIPELINE_DESC_WITHOUT_WEBRTC = '''
 appsrc name=source emit-signals=True is-live=True caps=video/x-raw,format=I420,width=640,height=480,framerate=10/1 ! 
 queue max-size-buffers=4 ! videoconvert ! autovideosink
'''

image_arr = np.zeros((480, 640), np.uint8)
counter = 0
is_push_buffer_allowed = True
appsrc = None

def ndarray_to_gst_buffer(array: np.ndarray) -> Gst.Buffer:
    """Converts numpy array to Gst.Buffer"""
    global image_arr, counter
    image_arr = np.random.randint(0,90,(480,640))
    counter += 1
    print(counter)
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


def push(data):
    global is_push_buffer_allowed
    if is_push_buffer_allowed:
        data1 = data.tobytes()
        buf = Gst.Buffer.new_allocate(None, len(data1), None)
        buf.fill(0, data1)
        # Create GstSample
        sample = Gst.Sample.new(buf, Gst.caps_from_string("video/x-raw,format=RGB,width=640,height=480,framerate=(fraction)30/1"), None, None)
        # Push Sample on appsrc
        gst_flow_return = appsrc.emit('push-sample', sample)
        print("--------push")
        if gst_flow_return != Gst.FlowReturn.OK:
            print('We got some error, stop sending data')
    else:
        #pass
        print('It is enough data for buffer....')

def start_feed(src, length):
    print("start feed")
    print("src", src)
    print("length", length)
    push(image_arr)

def stop_feed():
    print("stop feed")
    global is_push_buffer_allowed
    is_push_buffer_allowed = False


def start_pipeline():
    pipeline = Gst.parse_launch(PIPELINE_DESC_WITHOUT_WEBRTC)
    global appsrc
    appsrc = pipeline.get_by_name('source')
    
    appsrc.set_property("format", Gst.Format.TIME)
    appsrc.set_property('emit-signals', True)
    appsrc.set_property('max-bytes', 1000000)
    appsrc.set_property('do-timestamp', True)
    appsrc.connect('need-data', start_feed)
    appsrc.connect('enough-data', stop_feed)
    #appsrc.emit("push-buffer", ndarray_to_gst_buffer(image_arr))
    
    pipeline.set_state(Gst.State.PLAYING)
    
    
    #self._src.connect('enough-data', self.stop_feed)

    while True:
        import time
        time.sleep(0.2)
        
        print("."*50)
        




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
    
    start_pipeline()