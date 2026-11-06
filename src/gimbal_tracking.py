# Software and camera module setup: Yousef Ahmadzai
# Chassis printing, servo calibration, and IMU hardware setup: Timothy Titus

import time

import math

import cv2

import lgpio

import smbus

from picamera2 import Picamera2

from ultralytics import YOLO

# ==========================================

# CONFIGURATION

# ==========================================

WIDTH = 640

HEIGHT = 480

CENTER_X = WIDTH // 2

CENTER_Y = HEIGHT // 2

MODEL_PATH = "yolo26n.pt"

DEADZONE = 25

# Servo GPIO numbers (BCM numbering)

YAW_PIN = 17

PITCH_PIN = 27

ROLL_PIN = 22

# GPIO chip used by current Raspberry Pi 5 OS

GPIO_CHIP = 0

# Adjust to match your servos' safe range.

SERVO_MIN_US = 1000

SERVO_MAX_US = 2000

SERVO_MIN_ANGLE = 30

SERVO_MAX_ANGLE = 150

SERVO_CENTER = 90.0

# Maximum commanded change per update.

MAX_STEP = 2.0

# Degrees per pixel of tracking error.

TRACK_GAIN = 0.012

# Reverse an axis if it moves the wrong way.

YAW_DIRECTION = 1

PITCH_DIRECTION = -1

ROLL_DIRECTION = -1

# Roll leveling gain

ROLL_KP = 0.5

# MPU-9250

MPU_ADDRESS = 0x68

MPU_PWR_MGMT_1 = 0x6B

MPU_CONFIG = 0x1A

MPU_GYRO_CONFIG = 0x1B

MPU_ACCEL_CONFIG = 0x1C

MPU_ACCEL_XOUT_H = 0x3B

MPU_GYRO_XOUT_H = 0x43

ACCEL_SCALE = 16384.0

GYRO_SCALE = 131.0

# ==========================================

# SERVO CONTROLLER

# ==========================================

class ServoController:

    def __init__(self):

        self.handle = lgpio.gpiochip_open(GPIO_CHIP)

        self.pins = [YAW_PIN, PITCH_PIN, ROLL_PIN]

        self.angles = {

            YAW_PIN: SERVO_CENTER,

            PITCH_PIN: SERVO_CENTER,

            ROLL_PIN: SERVO_CENTER

        }

        for pin in self.pins:

            lgpio.gpio_claim_output(self.handle, pin, 0)

    def write(self, pin, angle):

        angle = max(

            SERVO_MIN_ANGLE,

            min(SERVO_MAX_ANGLE, angle)

        )

        pulse = SERVO_MIN_US + (

            angle / 180.0

        ) * (SERVO_MAX_US - SERVO_MIN_US)

        lgpio.tx_servo(

            self.handle,

            pin,

            int(pulse),

            50

        )

        self.angles[pin] = angle

    def move_toward(self, pin, target):

        current = self.angles[pin]

        change = max(

            -MAX_STEP,

            min(MAX_STEP, target - current)

        )

        self.write(pin, current + change)

    def center(self):

        for pin in self.pins:

            self.write(pin, SERVO_CENTER)

    def close(self):

        for pin in self.pins:

            lgpio.tx_servo(self.handle, pin, 0)

        time.sleep(0.1)

        lgpio.gpiochip_close(self.handle)

# ==========================================

# MPU-9250 CONTROLLER

# ==========================================

class MPU9250:

    def __init__(self):

        self.bus = smbus.SMBus(1)

        self.bus.write_byte_data(

            MPU_ADDRESS, MPU_PWR_MGMT_1, 0x01

        )

        time.sleep(0.1)

        # Gyro: +/- 250 degrees/sec

        # Accelerometer: +/- 2g

        self.bus.write_byte_data(

            MPU_ADDRESS, MPU_CONFIG, 0x03

        )

        self.bus.write_byte_data(

            MPU_ADDRESS, MPU_GYRO_CONFIG, 0x00

        )

        self.bus.write_byte_data(

            MPU_ADDRESS, MPU_ACCEL_CONFIG, 0x00

        )

        self.roll = 0.0

        self.pitch = 0.0

        self.last_time = time.monotonic()

        self.gyro_bias = [0.0, 0.0, 0.0]

        self.roll_reference = 0.0

        self.pitch_reference = 0.0

    def read_vector(self, address, scale):

        data = self.bus.read_i2c_block_data(

            MPU_ADDRESS, address, 6

        )

        values = []

        for i in range(0, 6, 2):

            raw = (data[i] << 8) | data[i + 1]

            if raw >= 32768:

                raw -= 65536

            values.append(raw / scale)

        return values

    def read_accel(self):

        return self.read_vector(

            MPU_ACCEL_XOUT_H, ACCEL_SCALE

        )

    def read_gyro(self):

        return self.read_vector(

            MPU_GYRO_XOUT_H, GYRO_SCALE

        )

    def accel_angles(self):

        ax, ay, az = self.read_accel()

        roll = math.degrees(

            math.atan2(ay, az)

        )

        pitch = math.degrees(

            math.atan2(

                -ax,

                math.sqrt(ay * ay + az * az)

            )

        )

        return roll, pitch

    def calibrate(self):

        print("Keep the gimbal completely still...")

        samples = 100

        sums = [0.0, 0.0, 0.0]

        for _ in range(samples):

            gyro = self.read_gyro()

            for i in range(3):

                sums[i] += gyro[i]

            time.sleep(0.01)

        self.gyro_bias = [

            value / samples for value in sums

        ]

        self.roll, self.pitch = self.accel_angles()

        self.roll_reference = self.roll

        self.pitch_reference = self.pitch

        self.last_time = time.monotonic()

        print("MPU calibration complete.")

    def update(self):

        now = time.monotonic()

        dt = min(now - self.last_time, 0.1)

        self.last_time = now

        gx, gy, gz = self.read_gyro()

        gx -= self.gyro_bias[0]

        gy -= self.gyro_bias[1]

        accel_roll, accel_pitch = self.accel_angles()

        alpha = 0.98

        self.roll = (

            alpha * (self.roll + gx * dt)

            + (1 - alpha) * accel_roll

        )

        self.pitch = (

            alpha * (self.pitch + gy * dt)

            + (1 - alpha) * accel_pitch

        )

        return (

            self.roll - self.roll_reference,

            self.pitch - self.pitch_reference

        )

    def close(self):

        self.bus.close()

# ==========================================

# CAMERA + YOLO

# ==========================================

def main():

    servo = None

    imu = None

    camera = None

    try:

        servo = ServoController()

        imu = MPU9250()

        servo.center()

        time.sleep(2)

        imu.calibrate()

        camera = Picamera2()

        config = camera.create_preview_configuration(

            main={

                "size": (WIDTH, HEIGHT),

                "format": "RGB888"

            }

        )

        camera.configure(config)

        camera.start()

        time.sleep(2)

        model = YOLO(MODEL_PATH)

        tracking_mode = True

        balancing_mode = False

        target_id = None

        yaw_target = SERVO_CENTER

        pitch_target = SERVO_CENTER

        print("3-Axis YOLO Gimbal Started")

        print("T = Tracking")

        print("B = Balancing only")

        print("C = Center and recalibrate")

        print("Q = Quit")

        while True:

            frame = camera.capture_array()

            # Read actual platform orientation.

            roll, pitch = imu.update()

            # Always draw the camera center.

            cv2.circle(

                frame,

                (CENTER_X, CENTER_Y),

                5, (0, 255, 0), -1

            )

            cv2.rectangle(

                frame,

                (CENTER_X - DEADZONE,

                 CENTER_Y - DEADZONE),

                (CENTER_X + DEADZONE,

                 CENTER_Y + DEADZONE),

                (0, 255, 0), 1

            )

            if tracking_mode:

                results = model.track(

                    frame,

                    persist=True,

                    tracker="bytetrack.yaml",

                    classes=[0],

                    verbose=False

                )

                boxes = results[0].boxes

                found_target = False

                if (

                    boxes is not None

                    and boxes.id is not None

                ):

                    ids = boxes.id.int().cpu().tolist()

                    coords = boxes.xyxy.cpu().tolist()

                    if target_id not in ids:

                        target_id = (

                            ids[0] if ids else None

                        )

                    for box, person_id in zip(

                        coords, ids

                    ):

                        if person_id != target_id:

                            continue

                        found_target = True

                        x1, y1, x2, y2 = map(

                            int, box

                        )

                        person_x = (x1 + x2) // 2

                        person_y = (y1 + y2) // 2

                        error_x = person_x - CENTER_X

                        error_y = person_y - CENTER_Y

                        # Update physical servo targets.

                        if abs(error_x) > DEADZONE:

                            yaw_target += (

                                YAW_DIRECTION

                                * TRACK_GAIN

                                * error_x

                            )

                        if abs(error_y) > DEADZONE:

                            pitch_target += (

                                PITCH_DIRECTION

                                * TRACK_GAIN

                                * error_y

                            )

                        yaw_target = max(

                            SERVO_MIN_ANGLE,

                            min(

                                SERVO_MAX_ANGLE,

                                yaw_target

                            )

                        )

                        pitch_target = max(

                            SERVO_MIN_ANGLE,

                            min(

                                SERVO_MAX_ANGLE,

                                pitch_target

                            )

                        )

                        cv2.rectangle(

                            frame,

                            (x1, y1), (x2, y2),

                            (0, 255, 0), 2

                        )

                        cv2.circle(

                            frame,

                            (person_x, person_y),

                            5, (0, 0, 255), -1

                        )

                        cv2.line(

                            frame,

                            (CENTER_X, CENTER_Y),

                            (person_x, person_y),

                            (255, 0, 0), 2

                        )

                        cv2.putText(

                            frame,

                            f"Target ID: {target_id}",

                            (x1, max(20, y1 - 10)),

                            cv2.FONT_HERSHEY_SIMPLEX,

                            0.6, (0, 255, 0), 2

                        )

                        break

                if not found_target:

                    # Hold last target angles.

                    target_id = None

                servo.move_toward(

                    YAW_PIN, yaw_target

                )

                servo.move_toward(

                    PITCH_PIN, pitch_target

                )

            # Roll leveling in both modes.

            if tracking_mode or balancing_mode:

                roll_target = (

                    SERVO_CENTER

                    + ROLL_DIRECTION * ROLL_KP * roll

                )

                servo.move_toward(

                    ROLL_PIN, roll_target

                )

            # Display telemetry.

            mode = (

                "TRACKING" if tracking_mode

                else "BALANCING"

            )

            cv2.putText(

                frame,

                f"Mode: {mode}",

                (10, 25),

                cv2.FONT_HERSHEY_SIMPLEX,

                0.6, (255, 255, 255), 2

            )

            cv2.putText(

                frame,

                f"Yaw: {servo.angles[YAW_PIN]:.1f} "

                f"Pitch: {servo.angles[PITCH_PIN]:.1f}",

                (10, 50),

                cv2.FONT_HERSHEY_SIMPLEX,

                0.5, (255, 255, 255), 1

            )

            cv2.putText(

                frame,

                f"IMU Roll: {roll:.1f} "

                f"Pitch: {pitch:.1f}",

                (10, 75),

                cv2.FONT_HERSHEY_SIMPLEX,

                0.5, (255, 255, 255), 1

            )

            cv2.imshow("3-Axis YOLO Gimbal", frame)

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):

                break

            elif key == ord("t"):

                tracking_mode = True

                balancing_mode = False

                target_id = None

                print("Tracking mode enabled")

            elif key == ord("b"):

                tracking_mode = False

                balancing_mode = True

                print("Balancing mode enabled")

            elif key == ord("c"):

                # Center before recalibrating.

                tracking_mode = False

                balancing_mode = False

                servo.center()

                yaw_target = SERVO_CENTER

                pitch_target = SERVO_CENTER

                target_id = None

                time.sleep(2)

                imu.calibrate()

                tracking_mode = True

                print("Gimbal centered and calibrated")

    finally:

        if camera is not None:

            camera.stop()

        cv2.destroyAllWindows()

        if servo is not None:

            servo.close()

        if imu is not None:

            imu.close()

if __name__ == "__main__":

    main()
