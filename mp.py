import mediapipe as mp
import cv2

mpPose = mp.solutions.pose
pose = mpPose.Pose()
mpDraw = mp.solutions.drawing_utils

class Model:
    def posenet_detect(self, image):
        
        imgRGB = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = pose.process(imgRGB)
        
        metadata = []
        
        if results.pose_landmarks:
            mpDraw.draw_landmarks(image, results.pose_landmarks, mpPose.POSE_CONNECTIONS)
            res = results.pose_landmarks.landmark
            for i in range(len(results.pose_landmarks.landmark)):
                x = res[i].x
                y = res[i].y
                z = res[i].z
                tmp = {"x": x, "y": y, "z": z}
                metadata.append(tmp)
            
        return metadata, image
