cmake_minimum_required(VERSION 3.20)
project(monitor_codec2 C)
include(FetchContent)
# Same revision, mode and float constants as WROOM and S3.
FetchContent_Declare(codec2_source
  GIT_REPOSITORY https://github.com/meshtastic/codec2.git
  GIT_TAG 3e347e0b70fc72af9357fbbd32b10a125321d6c5
)
FetchContent_MakeAvailable(codec2_source)
file(GLOB sources "${codec2_source_SOURCE_DIR}/src/*.c")
add_library(codec2 SHARED ${sources})
target_include_directories(codec2 PRIVATE "${codec2_source_SOURCE_DIR}/src")
target_compile_definitions(codec2 PRIVATE CODEC2_MODE_EN_DEFAULT=0 CODEC2_MODE_2400_EN=1)
target_compile_options(codec2 PRIVATE -fsingle-precision-constant)
target_link_libraries(codec2 PRIVATE m)
if(WIN32)
  if(NOT MINGW OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR "Windows build requires MinGW-w64 x64")
  endif()
  set(prefix win32-x86-64)
  set_target_properties(codec2 PROPERTIES PREFIX "")
  target_link_options(codec2 PRIVATE -static-libgcc)
else()
  string(TOLOWER "${CMAKE_SYSTEM_PROCESSOR}" arch)
  if(arch MATCHES "^(x86_64|amd64)$")
    set(prefix linux-x86-64)
  elseif(arch MATCHES "^(aarch64|arm64)$")
    set(prefix linux-aarch64)
  else()
    message(FATAL_ERROR "Unsupported bundled native platform")
  endif()
endif()
set(bundle "${CMAKE_CURRENT_SOURCE_DIR}/../target/native-resources")
add_custom_command(TARGET codec2 POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E make_directory "${bundle}/${prefix}" "${bundle}/META-INF/codec2"
  COMMAND ${CMAKE_COMMAND} -E copy "$<TARGET_FILE:codec2>" "${bundle}/${prefix}/$<TARGET_FILE_NAME:codec2>"
  COMMAND ${CMAKE_COMMAND} -E copy_directory "${codec2_source_SOURCE_DIR}/src" "${bundle}/META-INF/codec2/source/src"
  COMMAND ${CMAKE_COMMAND} -E copy "${codec2_source_SOURCE_DIR}/LICENSE" "${bundle}/META-INF/codec2/LICENSE"
  COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/CMakeLists.txt" "${bundle}/META-INF/codec2/CMakeLists.txt"
  COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/NOTICE.md" "${bundle}/META-INF/codec2/NOTICE.md"
)
