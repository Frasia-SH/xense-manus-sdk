cmake_minimum_required(VERSION 3.15)
project(manus_glove LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(PYBIND11_FINDPYTHON ON)
find_package(Python COMPONENTS Interpreter Development REQUIRED)
find_package(pybind11 CONFIG REQUIRED)

set(MANUS_SDK_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../vendor/manus")
set(MANUS_LIB_DIR "${MANUS_SDK_DIR}/lib")
set(MANUS_RUNTIME_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../runtime/linux-x86_64")

pybind11_add_module(manus_glove
    src/ManusGlove.cpp
    src/bindings.cpp
)

target_include_directories(manus_glove PRIVATE "${MANUS_SDK_DIR}/include")
target_link_libraries(manus_glove PRIVATE "${MANUS_LIB_DIR}/libManusSDK.so")

set_target_properties(manus_glove PROPERTIES
    BUILD_RPATH "\$ORIGIN/../../vendor/manus/lib;\$ORIGIN/../../runtime/linux-x86_64"
    INSTALL_RPATH "\$ORIGIN/../../vendor/manus/lib;\$ORIGIN/../../runtime/linux-x86_64"
)

target_link_options(manus_glove PRIVATE "-Wl,--disable-new-dtags")
