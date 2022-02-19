let peerConnection;
// webSocket = new WebSocket(signalingServer);
var [webSocket, setWebSocket] = useState(new WebSocket(signalingServer));
let rs;
const [streamId, setStreamId] = useState(null);

// const [remoteStream, setRemoteStream] = useState();
// const [cachedpeerConnection, setCachedpeerConnection] = useState();
// const [cachedRemotePC, setCachedRemotePC] = useState();
// const [socketId, setSocketId] = useState(0);
// const [isMuted, setIsMuted] = useState(false);

let sendChannel;
let connectionAttempts = 0;

const [remoteStream, setRemoteStream] = useState();
const [localStream, setLocalStream] = useState();
const [modalVisible, setModalVisible] = useState(false);
const [callStatus, setCallStatus] = useState(CALL_STATUSES.disconnected);
const orientation = useOrientation();
const { streamStore } = useStores();

// useEffect(() => {
//   navigation.setOptions({
//     headerRight: () => (
//       <Header
//         startCall={() => onConnectClicked(7145)}
//         handleSwitchCamera={handleSwitchCamera}
//       />
//     ),
//   });
//   return () => {};
// }, [navigation, startCall]);

function getOurId() {
    return Math.floor(Math.random() * (9000 - 10) + 10).toString();
}

function websocketServerConnect() {
    peer_id = getOurId();
    console.log(peer_id, 'peerid');
    connectionAttempts++;

    // if (connectionAttempts > 3) {
    //   setError(
    //     'Too many connection attempts, aborting. Refresh page to try again',
    //   );
    //   return;
    // }
    webSocket.onopen = () => {
        console.log('sent', peer_id);
        webSocket.send('HELLO ' + peer_id);
    };

    webSocket.onmessage = onServerMessage;
    webSocket.onerror = handleIncomingError;
    webSocket.onclose = onServerClose;
    // webSocket.addEventListener('message', onServerMessage);
    // webSocket.addEventListener('close', onServerClose);
    // webSocket.addEventListener('error', handleIncomingError);
}
useEffect(() => {
    // setTimeout(() => {
    //   onConnectClicked(stream);
    // }, 2000);

    // websocketServerConnect()
    websocketServerConnect();
    return () => {
        if (peerConnection) closeStreams();
    };
}, []);
function onConnectClicked(id) {
    webSocket.send('CONNECT');
}

async function startCall() {
    // You'll most likely need to use a STUN server at least. Look into TURN and decide if that's necessary for your project
    const configuration = {
        iceServers: [
            { urls: 'stun:stun.services.mozilla.com' },
            { urls: 'stun:stun.l.google.com:19302' },
        ],
    };

    peerConnection = new RTCPeerConnection(configuration);
    sendChannel = peerConnection.createDataChannel('label', null);
    sendChannel.onopen = handleDataChannelOpen;
    sendChannel.onmessage = (e) => {
        console.log('dataChannel.OnMessage:', e, e.data.type);
        sendChannel.send('Hi! (from browser)');
    };

    sendChannel.onerror = (error) => console.log('dataChannel.OnError:', error);

    sendChannel.onclose = (e) => console.log('dataChannel.OnClose', e);

    peerConnection.ondatachannel = onDataChannel;
    peerConnection.onaddstream = onAddStream;

    let rs = startLocalStream().then((stream) => {
        console.log('adding local stream');
        peerConnection.addStream(stream);
        setLocalStream(stream);
        return stream;
    });
    setCallStatus(CALL_STATUSES.connectedToCall);

    // could also use "addEventListener" for these callbacks, but you'd need to handle removing them as well
    peerConnection.addEventListener('icecandidate', (e) => {
        console.log('peerConnection icecandidate:', e.candidate);
        if (e?.candidate) {
            peerConnection.addIceCandidate(e.candidate);
            // prettier-ignore
            webSocket.send(JSON.stringify({ 'ice': e.candidate }));
        }
        console.log(`Error adding remotePC iceCandidate:`, peerConnection);
    });

    // AddTrack not supported yet, so have to use old school addStream instead
    // newStream.getTracks().forEach(track => peerConnection.addTrack(track, newStream));
    // try {
    //   const offer = await peerConnection.createOffer();
    //   console.log('Offer from peerConnection, setLocalDescription');
    //   await peerConnection.setLocalDescription(offer);

    //   await peerConnection.setRemoteDescription(remotePC.localDescription);
    // } catch (err) {
    //   console.error(err);
    // }
    return rs;
}
// useEffect(() => {

// }, [])
async function startLocalStream() {
    console.log('startLocalStream');
    // isFront will determine if the initial camera should face user or environment
    const isFront = true;
    const devices = await mediaDevices.enumerateDevices();

    const facing = isFront ? 'front' : 'environment';
    const videoSourceId = devices.find(
        (device) => device.kind === 'videoinput' && device.facing === facing,
    );
    const constraints = {
        audio: false,
        video: {
            facingMode: 'environment',
        },
    };
    return await mediaDevices.getUserMedia(constraints);
}

function onServerMessage(event) {
    let msg;
    switch (event.data) {
        case 'HELLO':
            setStatus('Registered with server, waiting for call');
            webSocket.send(`SESSION ${'11111'}`);
            return;
        case 'SESSION_OK':
            // setStatus('Starting negotiation');
            // if (wantRemoteOfferer()) {
            // startCall(null).then(generateOffer);
            // webSocket.send(`CONNECT`);

            setStatus('Sent OFFER_REQUEST, waiting for offer');
            return;
        // }
        // if (!peerConnection) startCall(null).then(generateOffer);
        case 'OFFER_REQUEST':
            // The peer wants us to set up and then send an offer
            if (!peerConnection) startCall(null).then(generateOffer);
            return;
        default:
            if (event.data.startsWith('ERROR')) {
                handleIncomingError(event.data);
                return;
            }
            if (event.data.startsWith('OFFER_REQUEST')) {
                // The peer wants us to set up and then send an offer
                if (!peerConnection) startCall(null).then(generateOffer);
            } else {
                // Handle incoming JSON SDP and ICE messages
                try {
                    msg = JSON.parse(event.data);
                } catch (e) {
                    if (e instanceof SyntaxError) {
                        handleIncomingError('Error parsing incoming JSON: ' + event.data);
                    } else {
                        handleIncomingError(
                            'Unknown error parsing response: ' + event.data,
                        );
                    }
                    return;
                }

                // Incoming JSON signals the beginning of a call
                if (!peerConnection) startCall(msg);

                if (msg.sdp != null) {
                    onIncomingSDP(msg.sdp);
                } else if (msg.ice != null) {
                    onIncomingICE(msg.ice);
                } else {
                    handleIncomingError('Unknown incoming JSON: ' + msg);
                }
            }
    }
}

function onDataChannel(event) {
    setStatus('Data channel created');
    let receiveChannel = event.channel;
    receiveChannel.onopen = (e) => console.log('open', peerConnection);
    receiveChannel.onmessage = (e) => {
        console.log('dataChannel.OnMessage:', e, e.data.type);
        sendChannel.send('Hi! (from browser)');
    };
    receiveChannel.onerror = (error) =>
        console.log('dataChannel.OnError:', error);
    receiveChannel.onclose = (e) => {
        setLocalStream();
        setRemoteStream(null);
        if (peerConnection) {
            peerConnection.close();
            peerConnection = null;
        }
        webSocket.close();

        console.log('dataChannel.OnClose', e);
    };
}

function onIncomingSDP(sdp) {
    console.log('onIncomingSDP');
    peerConnection

        .setRemoteDescription(sdp)
        .then(() => {
            setStatus('Remote SDP set');
            if (sdp.type != 'offer') return;
            setStatus('Got SDP offer');
            startLocalStream()
                .then((stream) => {
                    setStatus('Got local stream, creating answer');
                    peerConnection
                        .createAnswer()
                        .then(onLocalDescription)
                        .catch(setError);
                    setLocalStream(stream);
                })

                .catch(setError);
        })
        .catch(setError);
}

function onIncomingICE(ice) {
    console.log('onIncomingICE');
    let candidate = new RTCIceCandidate(ice);
    peerConnection
        .addIceCandidate(candidate)
        .catch((err) => console.log('error', err));
}

function generateOffer() {
    console.log('generateOffer');
    peerConnection
        .createOffer()
        .then((e) => onLocalDescription(e))
        .catch((err) => console.log('error', err));
}

function onLocalDescription(desc) {
    console.log('onLocalDescription');
    console.log('Got local description: ' + JSON.stringify(desc));

    peerConnection.setLocalDescription(desc).then(() => {
        setStatus('Sending SDP ' + desc.type);
        const sdp = { sdp: peerConnection.localDescription };
        webSocket.send(JSON.stringify(sdp));
    });
}

function onAddStream(event) {
    console.log('onAddStream');
    if (event) {
        console.log('Incoming stream', event);
        setRemoteStream(event.currentTarget._remoteStreams[0].toURL());
    }
}

function handleDataChannelOpen(event) {
    console.log('dataChannel.OnOpen', event);
}

function onServerClose(event) {
    setStatus('Disconnected from server');
    console.log(event, 'close');

    // websocketServerConnect();
    // Reset after a second
}

function setStatus(text) {
    console.log('status', text);
}

function resetState() {
    // This will call onServerClose()
    webSocket.close();
}

function setError(error) {
    console.log(error);
}

function handleIncomingError(error) {
    setError('ERROR: ' + error);

    resetState();
}
function resetVideo() {
    // Release the webcam and mic
    if (localStream)
        localStream.getTracks().forEach((track) => {
            track.stop();
        });

    // Reset the video element and stop showing the last received frame
}
const handleSwitchCamera = () => {
    if (localStream) {
        localStream.getVideoTracks().forEach((track) => {
            track._switchCamera();
        });
    }
};

const toggleMute = () => {
    if (!remoteStream) return;
    localStream.getAudioTracks().forEach((track) => {
        console.log(track.enabled ? 'muting' : 'unmuting', ' local track', track);
        track.enabled = !track.enabled;
    });
};
const closeStreams = () => {
    // if (streamStore.remoteStream) {
    //   peerConnection.removeStream(remoteStream);
    // }
    setCallStatus(CALL_STATUSES.disconnected);
    setLocalStream();
    setRemoteStream('');
    // peerConnection.close();
    peerConnection = null;
    resetState();

    // setTimeout(() => {
    //   websocketServerConnect();
    // }, 2000);
    // setCachedRemotePC();
    // setCachedpeerConnection();
};