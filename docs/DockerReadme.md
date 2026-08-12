# Docker Build Environment

The Dockerfiles provide optional Ubuntu-based environments for building the
MANUS C++ example and testing USB access. They are not required for building
the Python binding on a host with the normal compiler dependencies installed.

## Build

Run these commands from the repository root so Docker can access
`vendor/manus`:

```bash
docker build -f docker/Dockerfile -t xense-manus-sdk:linux .
```

When GitHub access requires a local HTTPS proxy:

```bash
docker build --network=host \
  --build-arg https_proxy=http://127.0.0.1:7897 \
  -f docker/Dockerfile \
  -t xense-manus-sdk:linux .
```

Only pass the proxy argument that is needed for Git traffic. The Dockerfile
builds grpc/protobuf inside the image and copies the vendor SDK from
`vendor/manus`.

## Run with USB access

```bash
docker run --rm -it --privileged \
  -v /dev:/dev \
  xense-manus-sdk:linux
```

Do not mount `/run/udev` or start udev inside a privileged container. Add the
MANUS device permissions on the host instead:

```bash
sudo tee /etc/udev/rules.d/99-manus.rules >/dev/null <<'RULES'
SUBSYSTEMS=="usb", ATTRS{idVendor}=="3325", MODE:="0666"
KERNEL=="hidraw*", ATTRS{idVendor}=="3325", MODE:="0666"
RULES
sudo udevadm control --reload-rules
sudo udevadm trigger
```

The image starts a shell. The recommended host-side build remains:

```bash
./build.sh cpp
```

The integrated variant can be built with:

```bash
docker build -f docker/Dockerfile.Integrated \
  -t xense-manus-sdk:integrated .
```
