ARG BRIDGE_BASE_IMAGE
FROM ${BRIDGE_BASE_IMAGE}

USER root
COPY --chown=appuser:appgroup sitecustomize.py /app/sitecustomize.py
COPY --chown=appuser:appgroup bridge_entrypoint.py /app/bridge_entrypoint.py
USER appuser

ENV ARCHMORPH_RELEASE_ROLE=bridge
CMD ["gunicorn", "-c", "gunicorn.conf.py", "bridge_entrypoint:app"]