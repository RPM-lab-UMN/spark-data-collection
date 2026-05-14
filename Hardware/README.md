# SPARK Hardware
BOM

## CAD
The [CAD](./CAD/) folder contains the [FreeCAD](https://snapcraft.io/freecad-realthunder) sorce files, along with *.3mf* files for 3D printing. 

- [D405 wrist camera mount STL](./CAD/camera_mounts/d405_wrist_mount/printable/d405_wrist_mount_30deg_37mm.stl)
- [D405 wrist camera mount editable CAD](./CAD/camera_mounts/d405_wrist_mount/source/)
- [D405 wrist camera mount docs](../data_pipeline/docs/d405-wrist-camera-mount.md)

## PCB
To assemble the electronics, fabricate the PCBs found in the [PCB](./PCB/) folder. The components can be found in the BOM. 

## Firmware
This project uses PlatformIO projects found in the [Firmware](./Firmware/) folder. The recommended method is to use the [PlatformIO](https://docs.platformio.org/en/latest/integration/ide/vscode.html) extension for VSCode.       

The electronics for this project uses one [ESP8266 NodeMCU microcontroller](./Firmware/SparkSerialTX/) for each SPARK unit, and one [STM32F103C8T6 Blue Pill](./Firmware/Motor_controller/) board for the haptic gloves. 
