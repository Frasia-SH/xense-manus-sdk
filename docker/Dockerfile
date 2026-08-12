# Copyright 2018 gRPC authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.#
#
# Based on https://hub.docker.com/r/grpc/cxx.

# To build (behind a proxy in mainland China; only git/https needs the proxy, apt must stay direct)
#   docker build --network=host --build-arg https_proxy=http://127.0.0.1:7897 -f ./Dockerfile -t manus-linux .
# Without a proxy:
#   docker build -f docker/Dockerfile -t manus-linux .

# To Run (Linux)
#   docker run --rm -it --privileged -v /dev:/dev manus-linux
# NOTE: do NOT mount /run/udev or start udev inside the container. On a desktop host
# this re-triggers the host's udev and kills your graphical session (kicks you back to
# the login screen). Install the device rules on the HOST instead (see 99-manus.rules
# block below), then the container only needs -v /dev:/dev for USB HID access.

# The build context is the repository root. See docs/DockerReadme.md for run
# commands and host-side USB permission setup.

# To Run (Windows)
#   docker run -p 5000:5000 -i -t manus-linux /bin/bash

# FROM ubuntu:jammy as build
FROM ubuntu:focal as build
LABEL description="Visual Studio Manus SDK Build container"

# Proxy for build (passed via --build-arg, used by git/apt over --network=host)
ARG http_proxy
ARG https_proxy

ENV TZ=Europe/Amsterdam
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update && apt-get install -y \
  build-essential \
  # Required to install GRPC
  git \
  libtool \
  libzmq3-dev \
  zlib1g-dev \
  # Required for core integrated
  libusb-1.0-0-dev \
  libudev-dev \
  # Only required for building the minimal client
  libncurses5-dev \ 
  # Only required for visual studio debugging
  gdb \
  && apt-get clean

ENV GRPC_RELEASE_TAG="v1.28.1"

RUN git clone -b ${GRPC_RELEASE_TAG} https://github.com/grpc/grpc /var/local/git/grpc && \
    cd /var/local/git/grpc && \
    git submodule update --init --recursive

RUN echo "-- installing protobuf" && \
    cd /var/local/git/grpc/third_party/protobuf && \
    ./autogen.sh && ./configure --enable-shared && \
    make -j$(nproc) && make -j$(nproc) check && make install && make clean && ldconfig

RUN echo "-- installing grpc" && \
    cd /var/local/git/grpc && \
    make -j$(nproc) && make install && make clean && ldconfig

# configure SSH for communication with Visual Studio 
RUN apt-get update && apt-get install -y openssh-server
RUN mkdir -p /var/run/sshd
RUN echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config && \ 
   ssh-keygen -A 

# please make sure to change the password
RUN id -u manus >/dev/null 2>&1 || useradd -m -d /home/manus -s /bin/bash -G sudo manus && \
echo "manus:password" | chpasswd

# copy dependencies to ~/ManusSDK/ directory
COPY vendor/manus /home/manus/ManusSDK

# Add read/write permissions for manus devices
RUN apt-get update && apt-get install -y udev
RUN echo "# HIDAPI/libusb" > /etc/udev/rules.d/99-manus.rules && \
    echo "SUBSYSTEMS==\"usb\", ATTRS{idVendor}==\"3325\", MODE:=\"0666\"" >> /etc/udev/rules.d/99-manus.rules && \
    echo "# HIDAPI/hidraw" >> /etc/udev/rules.d/99-manus.rules && \
    echo "KERNEL==\"hidraw*\", ATTRS{idVendor}==\"3325\", MODE:=\"0666\"" >> /etc/udev/rules.d/99-manus.rules

# change default SSH port to 5000 to not conflict with system ssh in host mode
RUN echo "Port 5000" >> /etc/ssh/sshd_config

# Start SSH only. Do NOT run "service udev start" here: in a --privileged container
# that shares the host /dev it restarts the host udev and kills the desktop session.
# Device permissions are handled by the 99-manus.rules installed on the HOST.
ENTRYPOINT service ssh start && /bin/bash

EXPOSE 5000
