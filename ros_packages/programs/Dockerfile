# pib-ros-base:humble = ros:humble-ros-core + build-essential/colcon/pip/curl
# (siehe ros_packages/base/Dockerfile) - keine weiteren apt-Pakete noetig hier.
FROM pib-ros-base:humble

SHELL ["/bin/bash", "-c"]

WORKDIR /app

COPY ./pib_blockly/pib_blockly_client /tmp/pib_blockly_client
COPY ./pib_api/client /tmp/pib_api_client
COPY ./ros_packages/motors/pib_motors /tmp/pib_motors
RUN pip install /tmp/pib_blockly_client && \
    pip install /tmp/pib_api_client && \
    pip install /tmp/pib_motors && \
    pip install requests==2.32.3 && \
    pip install paramiko==3.5.1 && \
    pip install tinkerforge



COPY ./ros_packages/datatypes ros2_ws/datatypes
COPY ./ros_packages/programs ros2_ws/programs

RUN cd ros2_ws && \
    source /opt/ros/humble/setup.bash && \
    colcon build

COPY ./ros_packages/ros_entrypoint.sh /

RUN chmod +x /ros_entrypoint.sh


ENTRYPOINT ["/ros_entrypoint.sh"]
CMD ["bash"]