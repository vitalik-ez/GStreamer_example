import os
import cv2
import uuid
import time
from datetime import datetime

import numpy as np
from multiprocessing import Process, Value, Manager

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstVideo', '1.0')
from gi.repository import Gst, GObject, GLib, GstVideo


gi.require_version('GstWebRTC', '1.0')
from gi.repository import GstWebRTC
gi.require_version('GstSdp', '1.0')
from gi.repository import GstSdp
gi.require_version('GstApp', '1.0')


Gst.init(None)
image_arr = np.zeros((2160, 3840), np.uint8)

counter = 0
def gst_to_opencv(sample):
    buf = sample.get_buffer()
    buff = buf.extract_dup(0, buf.get_size())

    caps = sample.get_caps().get_structure(0)
    w, h = caps.get_value('width'), caps.get_value('height')

    # frmt_str = caps.get_value('format') 
    # video_format = GstVideo.VideoFormat.from_string(frmt_str)
    # c = 2  utils.get_num_channels(video_format)

    arr = np.ndarray(shape=(h, w),
                     buffer=buff,
                     dtype=np.uint8)
    
    global counter
    counter += 1
    print(counter)
    # remove single dimensions (ex.: grayscale image)
    #arr = np.squeeze(arr)  
    return arr


def new_buffer(sink, data):
    global image_arr
    sample = sink.emit("pull-sample") # receive gstreamer sample - Gst.Sample, wrapper on Gst.Buffer with additional info
    # buf = sample.get_buffer()
    # print "Timestamp: ", buf.pts
    arr = gst_to_opencv(sample)
    image_arr = arr
    return Gst.FlowReturn.OK



def read_4k_cameras(sensor_id: int = 0, output_path: str = "", fps: int = 30):
    now = datetime.now().strftime("CAMERA_{}_%Y.%m.%d_%H:%M:%S".format(sensor_id))
    path = os.path.join(output_path, now)
    if not os.path.exists(path):
        os.mkdir(path)

    PIPELINE = 'nvarguscamerasrc sensor-id={} ! '.format(sensor_id)
    PIPELINE += 'video/x-raw(memory:NVMM), width=3840, height=2160, format=NV12, framerate=30/1 ! '
    PIPELINE += 'nvvidconv flip-method=2 interpolation-method=5 ! '
    PIPELINE += 'tee name=t t. ! '
    PIPELINE += 'queue ! appsink name=sink t. ! ' # t.
    PIPELINE += 'queue ! clockoverlay time-format="%d-%m-%Y\ %a\ %H:%M:%S" ! textoverlay text="CAMERA {}" valignment=bottom halignment=left font-desc="Sans, 15" ! nvvidconv ! '.format(sensor_id)
    PIPELINE += 'omxh264enc control-rate=2 bitrate=4000000 ! '
    PIPELINE += 'splitmuxsink location={}/video%02d.mp4 max-size-time={}'.format(path, int(1e10))
    
    #PIPELINE += 'queue ! nvvidconv ! omxvp8enc control-rate=2 bitrate=4000000 ! webmmux ! filesink location=video.mp4 '
    #PIPELINE += 'mp4mux ! splitmuxsink location=recorded_videos/video%02d.mp4 max-size-time=10000000000 max-size-bytes=1000000 '
    #PIPELINE += '! splitmuxsink location=recorded_videos/video%02d.mov max-size-time=10000000000 max-size-bytes=1000000'
    print(PIPELINE)
    
    pipe = Gst.parse_launch(PIPELINE)
    sink = pipe.get_by_name("sink")

    sink.set_property("emit-signals", True)
    # sink.set_property("max-buffers", 2)
    # # sink.set_property("drop", True)
    # # sink.set_property("sync", False)

    caps = Gst.caps_from_string("video/x-raw, format=(string){BGR, GRAY8}; video/x-bayer,format=(string){rggb,bggr,grbg,gbrg}")
    sink.set_property("caps", caps)
    sink.connect("new-sample", new_buffer, sink)
    

    #bus = pipe.get_bus()
    #bus.add_signal_watch()
    #bus.connect('message::error', on_error)
    
    ret = pipe.set_state(Gst.State.PLAYING)
    if ret == Gst.StateChangeReturn.FAILURE:
        print("Unable to set the pipeline to the playing state.")
        exit(-1)

    # Wait until error or EOS
    bus = pipe.get_bus()

    time_loop = time.time()
    time_save_file = time.time()
    counter = 0
    # Parse message
    while True:
        message = bus.timed_pop_filtered(10000, Gst.MessageType.ANY)

        #if image_arr is not None:
        # Save image every 5 seconds
        if time.time() - time_save_file > 5:
            # Preprocessing
            ret,thresh1 = cv2.threshold(image_arr,127,255,cv2.THRESH_BINARY)
            path = os.getcwd() + f"/recorded_videos/images/{counter}.jpg"
            cv2.imwrite(path, thresh1)
            time_save_file = time.time()
            counter += 1
            #break
        
        if time.time() - time_loop > 60:
            break
            
        '''
        if message:
            if message.type == Gst.MessageType.ERROR:
                err, debug = message.parse_error()
                print(("Error received from element %s: %s" % (
                    message.src.get_name(), err)))
                print(("Debugging information: %s" % debug))
                break
            elif message.type == Gst.MessageType.EOS:
                print("End-Of-Stream reached.")
                break
            elif message.type == Gst.MessageType.STATE_CHANGED:
                if isinstance(message.src, Gst.Pipeline):
                    old_state, new_state, pending_state = message.parse_state_changed()
                    print(("Pipeline state changed from %s to %s." %
                        (old_state.value_nick, new_state.value_nick)))
            else:
                print("Unexpected message received.")
        '''
    # Free resources
    pipe.set_state(Gst.State.NULL)

def main():

    BASE_PATH = os.getcwd()
    output_path = os.path.join(BASE_PATH, 'recorded_videos')
    if not os.path.exists(output_path):
        os.mkdir(output_path)

    Gst.init(None)
    
    read_first_camera = Process(target=read_4k_cameras, args=(1, output_path))
    read_first_camera.start()

    #read_second_camera = Process(target=read_4k_cameras, args=(1,))
    #read_second_camera.start()

    read_first_camera.join()
    #read_second_camera.join()

if __name__ == '__main__':
    main()


