cmake_minimum_required(VERSION 3.15)
project(manus_minimal_client LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(MANUS_SDK_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../vendor/manus")
set(MANUS_LIB_DIR "${MANUS_SDK_DIR}/lib")
set(MANUS_RUNTIME_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../runtime/linux-x86_64")

find_package(Curses REQUIRED)

add_executable(SDKMinimalClient
    ClientPlatformSpecific.cpp
    SDKMinimalClient.cpp
)

target_include_directories(SDKMinimalClient PRIVATE
    "${MANUS_SDK_DIR}/include"
    "${CURSES_INCLUDE_DIRS}"
)

target_link_libraries(SDKMinimalClient PRIVATE
    "${MANUS_LIB_DIR}/libManusSDK.so"
    "${MANUS_RUNTIME_DIR}/libgrpc++.so"
    "${MANUS_RUNTIME_DIR}/libgrpc.so"
    "${MANUS_RUNTIME_DIR}/libprotobuf.so"
    "${MANUS_RUNTIME_DIR}/libgpr.so"
    "${CURSES_LIBRARIES}"
)

set_target_properties(SDKMinimalClient PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../../build/cpp"
    BUILD_RPATH "\$ORIGIN/../../vendor/manus/lib;\$ORIGIN/../../runtime/linux-x86_64"
    INSTALL_RPATH "\$ORIGIN/../../vendor/manus/lib;\$ORIGIN/../../runtime/linux-x86_64"
)

target_link_options(SDKMinimalClient PRIVATE "-Wl,--disable-new-dtags")
