# pib-ros-base:humble = ros:humble-ros-core + build-essential/colcon/pip/curl
# (siehe ros_packages/base/Dockerfile) - hier nur noch das Service-Spezifische.
FROM pib-ros-base:humble

SHELL ["/bin/bash", "-c"]

RUN apt-get update && apt-get install --no-install-recommends -y \
    python3-tk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install requests==2.32.3 && \
    pip install pillow && \
    pip install qrcode

COPY ./pib_api/client ./client
RUN pip install ./client

COPY ./ros_packages/datatypes ros2_ws/datatypes
COPY ./ros_packages/display ros2_ws/display

RUN cd ros2_ws && \
    source /opt/ros/humble/setup.bash && \
    colcon build

COPY ./ros_packages/ros_entrypoint.sh /

RUN chmod +x /ros_entrypoint.sh

ENTRYPOINT ["/ros_entrypoint.sh"]

CMD ["bash"]