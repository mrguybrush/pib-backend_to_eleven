from setuptools import setup

package_name = "gesture_control"

setup(
    name=package_name,
    version="0.0.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="pib",
    maintainer_email="team@pib.rocks",
    description="Applies hand/body landmarks streamed from a browser to pib's motors",
    license="Agpl3.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": ["gesture_control = gesture_control.gesture_node:main"],
    },
)
