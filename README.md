# GStreamer_example

gcc webrtc-sendrecv.c $(pkg-config --cflags --libs gstreamer-webrtc-1.0 gstreamer-sdp-1.0 libsoup-2.4 json-glib-1.0) -o webrtc-sendrecv && GST_DEBUG=1 ./webrtc-sendrecv --peer-id=691