FROM debian:13-slim

USER nobody

CMD ["bash", "-lc", "echo hello world"]
