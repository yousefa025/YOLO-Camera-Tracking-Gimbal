# Software notes

These notes describe the supplied `src/gimbal_tracking.py` file. They document its existing behavior and defaults.

## Camera and tracking defaults

| Setting | Value in the script |
| --- | --- |
| Capture size | 640 × 480 pixels |
| Camera format | `RGB888` |
| Model path | `yolo26n.pt` |
| Detected class | Class 0, person, with the intended COCO model |
| Tracker | `bytetrack.yaml` with persistent tracker state |
| Deadzone | ±25 pixels on each image axis |
| Tracking gain | 0.012 degrees per pixel per loop update |
| Maximum servo change | 2 degrees per loop update |

The target error is the person's bounding-box center minus the image center. A positive horizontal error means the person is to the right of the image center. The direction constants determine how that error changes each servo target.

When the selected ID is unavailable, the script chooses the first currently returned tracking ID, if any. When no target is returned, it clears the selected ID and retains the yaw and pitch targets. This provides position hold, but not persistent identification of a particular person after that person disappears.

## Servo configuration

The GPIO numbers below use BCM numbering, as specified in the source.

| Setting | Value in the script |
| --- | --- |
| Yaw GPIO | 17 |
| Pitch GPIO | 27 |
| Roll GPIO | 22 |
| GPIO chip | 0 |
| Servo center | 90 degrees |
| Command limits | 30 to 150 degrees |
| Pulse mapping | 1000 to 2000 microseconds over a nominal 0 to 180 degrees |
| Servo frequency | 50 Hz |
| Direction constants | Yaw +1, pitch −1, roll −1 |

These are software defaults, not a verified wiring diagram. GPIO chip numbering, servo direction, pulse calibration, and mechanical travel need to match the particular Pi installation and assembled mount.

## Orientation feedback

The `MPU9250` class opens I²C bus 1 at address `0x68`. It configures ±2 g accelerometer scaling and ±250 degrees per second gyroscope scaling. Calibration averages 100 gyro samples and records the starting roll and pitch as reference angles.

A complementary filter combines gyro integration with accelerometer angles. The script uses a 0.98 gyro weighting. It calculates both roll and pitch, but only the roll estimate affects the leveling servo. The roll proportional gain is 0.5. Magnetometer data is not read.

Tracking mode updates yaw and pitch from image errors while also leveling roll. Balancing mode continues roll leveling and leaves yaw and pitch at their last commanded positions.

## Runtime and verification

Startup initializes the GPIO outputs and IMU, centers the servos, calibrates the IMU, and then starts the camera and detector. There is no camera-only fallback in this supplied script.

The code was syntax-checked while preparing the repository. It has not been executed against physical hardware in this environment. The exact model weights, original dependency versions, and script revision used for each recording were not supplied. No frame rate, tracking accuracy, or stabilization performance measurement is claimed here.
