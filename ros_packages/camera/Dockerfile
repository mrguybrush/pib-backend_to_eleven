FROM luxonis/depthai-ros:humble-arm64-latest
SHELL ["/bin/bash", "-c"]

WORKDIR /app
COPY ./datatypes ros2_ws/datatypes
COPY ./camera ros2_ws/camera

RUN set -xe \
    && apt-get update \
    && apt-get install -y python3-pip

RUN pip install depthai==2.25.1.0

# On-device NN blobs (experimentelle Bewegungserfassung direkt auf der
# OAK-D-VPU, siehe oak_d_lite/stereo.py): MoveNet single-pose lightning
# (17 Koerper-Keypoints) + MediaPipe hand landmark lite (Hand auf/zu).
# Quelle: geaxgx/depthai_movenet bzw. geaxgx/depthai_hand_tracker (MIT).
ADD https://raw.githubusercontent.com/geaxgx/depthai_movenet/main/models/movenet_singlepose_lightning_U8_transpose.blob /models/movenet.blob
ADD https://raw.githubusercontent.com/geaxgx/depthai_hand_tracker/main/models/hand_landmark_lite_sh4.blob /models/hand_landmark_lite.blob

RUN cd ros2_ws && \
    source /opt/ros/humble/setup.bash && \
    colcon build

COPY ./ros_entrypoint.sh /

RUN chmod +x /ros_entrypoint.sh

ENTRYPOINT ["/ros_entrypoint.sh"]
CMD ["bash"]
