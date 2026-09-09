FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Compilers for the BUILDER stage only -- they never reach the runtime
# image (that stage copies just /opt/venv), so this costs build time, not
# image size.
#
# Needed because the deployment target is Oracle's Always Free
# VM.Standard.A1.Flex, which is Ampere ARM (aarch64). Most of the
# dependency set ships aarch64 manylinux wheels, but the set is large and
# a single package without one falls back to building from source -- which
# fails outright on python:*-slim, since it has no gcc. That failure
# surfaces deep inside a `pip install` log on the VM, at the least
# convenient moment. Cheap insurance; drop it if you pin to x86 and
# confirm every wheel resolves.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY . .
RUN pip install --no-cache-dir .

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home appuser \
 && install -d -m 0755 -o appuser -g appuser /home/appuser/.tradingagents
USER appuser
WORKDIR /home/appuser/app

COPY --from=builder --chown=appuser:appuser /build .

ENTRYPOINT ["tradingagents"]
