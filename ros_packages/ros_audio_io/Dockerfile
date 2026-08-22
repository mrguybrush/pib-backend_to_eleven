# pib-ros-base:humble = ros:humble-ros-core + build-essential/colcon/pip/curl
# (siehe ros_packages/base/Dockerfile) - hier nur noch das Service-Spezifische.
FROM pib-ros-base:humble

SHELL ["/bin/bash", "-c"]

WORKDIR /app

# Install necessary dependencies
RUN apt-get update --fix-missing && \
    apt-get install --no-install-recommends -y \
        ros-humble-rclpy \
        ros-humble-std-msgs \
        python3-usb \
        portaudio19-dev \
        pulseaudio \
        libusb-1.0-0-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python audio packages
RUN pip install pyaudio numpy scipy taskgroup

COPY ./pib_api/client ./client
RUN pip install ./client

COPY ./ros_packages/datatypes ros2_ws/datatypes
COPY ./ros_packages/ros_audio_io ros2_ws/ros_audio_io

RUN cd ros2_ws && \
    source /opt/ros/humble/setup.bash && \
    colcon build

COPY ./ros_packages/ros_entrypoint.sh /

RUN chmod +x /ros_entrypoint.sh

ENTRYPOINT ["/ros_entrypoint.sh"]
CMD ["bash"]

