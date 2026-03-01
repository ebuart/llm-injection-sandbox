# llm-injection-sandbox — isolated scenario environment
#
# Minimal Alpine image used as the ClientA sandbox.
# No network, no external tools, no shell beyond POSIX sh.
#
# Build:
#   docker build -t llm-injection-sandbox:latest docker/
#
# The container is never run interactively; the DockerSandbox class
# in sandbox/core/docker_sandbox.py manages its full lifecycle.

FROM alpine:3.20

RUN addgroup -S sandbox \
 && adduser  -S sandbox -G sandbox

WORKDIR /workspace
RUN chown sandbox:sandbox /workspace

USER sandbox

# Kept alive by DockerSandbox.start(); stopped and removed by DockerSandbox.stop()
CMD ["sleep", "infinity"]
