| Supported Targets | ESP32 | ESP32-C2 | ESP32-C3 | ESP32-C5 | ESP32-C6 | ESP32-C61 | ESP32-H2 | ESP32-H21 | ESP32-H4 | ESP32-P4 | ESP32-S2 | ESP32-S3 | Linux |
| ----------------- | ----- | -------- | -------- | -------- | -------- | --------- | -------- | --------- | -------- | -------- | -------- | -------- | ----- |

# Hello World Example

Starts a FreeRTOS task to print "Hello World".

(See the README.md file in the upper level 'examples' directory for more information about examples.)

## How to use example

Follow detailed instructions provided specifically for this example.

Select the instructions depending on Espressif chip installed on your development board:

- [ESP32 Getting Started Guide](https://docs.espressif.com/projects/esp-idf/en/stable/get-started/index.html)
- [ESP32-S2 Getting Started Guide](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s2/get-started/index.html)


## Example folder contents

The project **hello_world** contains one source file in C language [hello_world_main.c](main/hello_world_main.c). The file is located in folder [main](main).

ESP-IDF projects are built using CMake. The project build configuration is contained in `CMakeLists.txt` files that provide set of directives and instructions describing the project's source files and targets (executable, library, or both).

Below is short explanation of remaining files in the project folder.

```
├── CMakeLists.txt
├── pytest_hello_world.py      Python script used for automated testing
├── main
│   ├── CMakeLists.txt
│   └── hello_world_main.c
└── README.md                  This is the file you are currently reading
```

For more information on structure and contents of ESP-IDF projects, please refer to Section [Build System](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/build-system.html) of the ESP-IDF Programming Guide.

## Troubleshooting

* Program upload failure

    * Hardware connection is not correct: run `idf.py -p PORT monitor`, and reboot your board to see if there are any output logs.
    * The baud rate for downloading is too high: lower your baud rate in the `menuconfig` menu, and try again.

## Technical support and feedback

Please use the following feedback channels:

* For technical queries, go to the [esp32.com](https://esp32.com/) forum
* For a feature request or bug report, create a [GitHub issue](https://github.com/espressif/esp-idf/issues)

We will get back to you as soon as possible.

## PLC UART 배선

PLC는 UART1, 9600bps, 8N1을 사용합니다. `main/board_config.h` 기준:

| 기능 | P4 GPIO | 연결 |
|---|---|---|
| PLC TX | **GPIO47** (GPIO46/47 역할 교환) | 레벨 시프터 3.3V 입력 → 모뎀 RX |
| PLC RX | GPIO46 | 모뎀 TX → 적합한 3.3V 레벨 변환 → P4 RX |

GPIO 번호는 커넥터의 물리 핀 순번이 아닙니다. GPIO46/47은 저장소 내 다른 기능에
배정되지 않았지만, 실제 보드에서 해당 핀이 외부에 노출되고 다른 회로에 연결되지
않았는지 보드 핀맵을 확인하세요.

변경 후 P4만 빌드/업로드하고, 전원을 끈 상태에서 기존 GPIO46 TX 선을 GPIO47로, GPIO47 RX 선을 GPIO46으로
옮깁니다. Pi의 UART 포트와 WROOM/S3 설정은 이 변경으로 달라지지 않습니다.
먼저 레벨 시프터 연결을 분리한 상태에서 GPIO47의 UART idle HIGH가 약 3.3V인지
측정하고, 이후 레벨 시프터와 모뎀을 단계적으로 연결하여 파형을 비교하세요.
외부 회로 연결 후 전압이 떨어지면 연결을 중단하고 해당 회로를 점검하세요.
P4 GPIO에 5V를 직접 인가하지 마세요. GPIO48 손상 여부와 CRC 오류 해결 여부는
아직 확정되지 않았으며, 핀 변경은 비교 진단을 위한 것입니다.
