# Codec2 native bundle

Source: https://github.com/meshtastic/codec2
Revision: 3e347e0b70fc72af9357fbbd32b10a125321d6c5 (same as WROOM/S3)
Codec2 copyright holders and LGPL terms are in the accompanying LICENSE and source file headers.

The JAR includes the unmodified C source and LICENSE under META-INF/codec2, plus
our CMake recipe. No static linking into Java: JNA loads the replaceable shared library.
CODEC2_LIBRARY may point to a compatible user-built library instead of the bundle.
To rebuild, use this repository's monitoring-server/native/CMakeLists.txt with
CMake, Ninja and GCC (MinGW-w64 x64 on Windows), or mvn -Pnative-codec verify.
JNA is a separate Maven dependency, distributed with its upstream license notices.
