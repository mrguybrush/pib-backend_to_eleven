# pib-ros-base:humble = ros:humble-ros-core + build-essential/colcon/pip/curl
# (siehe ros_packages/base/Dockerfile) - keine weiteren apt-Pakete noetig hier.
FROM pib-ros-base:humble

SHELL ["/bin/bash", "-c"]

WORKDIR /app

COPY ./pib_api/client ./client
RUN pip install ./client

COPY ./ros_packages/datatypes ros2_ws/datatypes
COPY ./ros_packages/gesture_control ros2_ws/gesture_control

RUN cd ros2_ws && \
    source /opt/ros/humble/setup.bash && \
    colcon build

COPY ./ros_packages/ros_entrypoint.sh /

RUN chmod +x /ros_entrypoint.sh

ENTRYPOINT ["/ros_entrypoint.sh"]
CMD ["bash"]
