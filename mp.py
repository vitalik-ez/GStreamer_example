import mediapipe as mp
import cv2


mpDraw = mp.solutions.drawing_utils

mpPose = mp.solutions.pose
pose = mpPose.Pose()

mpHolistic = mp.solutions.holistic
holistic = mpHolistic.Holistic()
mp_drawing_styles = mp.solutions.drawing_styles

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


    def holistic_detect(self, image):
        imgRGB = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = holistic.process(imgRGB)
        
        metadata = []
        
        if results.pose_landmarks and results.face_landmarks:
            #mpDraw.draw_landmarks(image, results.pose_landmarks, mpPose.POSE_CONNECTIONS)
            
            mpDraw.draw_landmarks(
                image,
                results.face_landmarks,
                mpHolistic.FACEMESH_CONTOURS,
                landmark_drawing_spec=None,
                connection_drawing_spec=mp_drawing_styles
                .get_default_face_mesh_contours_style())
            mpDraw.draw_landmarks(
                image,
                results.pose_landmarks,
                mpHolistic.POSE_CONNECTIONS,
                landmark_drawing_spec=mp_drawing_styles
                .get_default_pose_landmarks_style())


            res = results.pose_landmarks.landmark
            for i in range(len(results.pose_landmarks.landmark)):
                x = res[i].x
                y = res[i].y
                z = res[i].z
                tmp = {"x": x, "y": y, "z": z}
                metadata.append(tmp)
            
        return metadata, image
