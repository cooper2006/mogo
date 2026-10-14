FROM alpine:3.20
RUN apk add --no-cache python3
COPY fwd.py /fwd.py
ENTRYPOINT ["python3", "/fwd.py"]
