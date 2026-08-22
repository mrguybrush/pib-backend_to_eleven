# pib-ros-base:humble = ros:humble-ros-core + build-essential/colcon/pip/curl
# (siehe ros_packages/base/Dockerfile) - hier nur noch das Service-Spezifische.
FROM pib-ros-base:humble

SHELL ["/bin/bash", "-c"]

RUN apt update && apt upgrade -y && apt install -y \
    ros-$ROS_DISTRO-rosbridge-server&& \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY ./datatypes ros2_ws/datatypes

RUN cd ros2_ws && \
    source /opt/ros/humble/setup.bash && \
    colcon build

COPY ./ros_entrypoint.sh /

RUN chmod +x /ros_entrypoint.sh

EXPOSE 9090

ENTRYPOINT ["/ros_entrypoint.sh"]
CMD ["bash"]
