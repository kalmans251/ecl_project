# ESP-IDF first evaluates component requirements in CMake script mode.
if(CMAKE_BUILD_EARLY_EXPANSION)
    idf_component_register()
    return()
endif()

# Same pinned vocoder source as the S3 encoder. Downloaded only during configure.
include(FetchContent)
FetchContent_Declare(ecl_codec2
    GIT_REPOSITORY https://github.com/meshtastic/codec2.git
    GIT_TAG 3e347e0b70fc72af9357fbbd32b10a125321d6c5
)
FetchContent_MakeAvailable(ecl_codec2)
file(GLOB codec2_sources "${ecl_codec2_SOURCE_DIR}/src/*.c")
idf_component_register(SRCS ${codec2_sources} INCLUDE_DIRS "${ecl_codec2_SOURCE_DIR}/src")
target_compile_definitions(${COMPONENT_LIB} PRIVATE CODEC2_MODE_EN_DEFAULT=0 CODEC2_MODE_2400_EN=1)
target_compile_options(${COMPONENT_LIB} PRIVATE -fsingle-precision-constant)
