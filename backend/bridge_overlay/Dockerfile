ARG BRIDGE_BASE_IMAGE
ARG ARCHMORPH_SOURCE_SHA
ARG ARCHMORPH_SOURCE_REPOSITORY
ARG ARCHMORPH_BUILD_WORKFLOW
ARG ARCHMORPH_BUILD_RUN_ID
ARG ARCHMORPH_BUILD_RUN_ATTEMPT
ARG ARCHMORPH_IMAGE_PLATFORM
ARG ARCHMORPH_SCHEMA_ACCEPTED_REVISIONS
ARG ARCHMORPH_SCHEMA_CONTRACT_DIGEST
FROM ${BRIDGE_BASE_IMAGE}

ARG ARCHMORPH_SOURCE_SHA
ARG ARCHMORPH_SOURCE_REPOSITORY
ARG ARCHMORPH_BUILD_WORKFLOW
ARG ARCHMORPH_BUILD_RUN_ID
ARG ARCHMORPH_BUILD_RUN_ATTEMPT
ARG ARCHMORPH_IMAGE_PLATFORM
ARG ARCHMORPH_SCHEMA_ACCEPTED_REVISIONS
ARG ARCHMORPH_SCHEMA_CONTRACT_DIGEST

LABEL org.opencontainers.image.revision="${ARCHMORPH_SOURCE_SHA}" \
	org.opencontainers.image.source="https://github.com/${ARCHMORPH_SOURCE_REPOSITORY}" \
	io.archmorph.build.workflow="${ARCHMORPH_BUILD_WORKFLOW}" \
	io.archmorph.build.run-id="${ARCHMORPH_BUILD_RUN_ID}" \
	io.archmorph.build.run-attempt="${ARCHMORPH_BUILD_RUN_ATTEMPT}" \
	io.archmorph.image.platform="${ARCHMORPH_IMAGE_PLATFORM}" \
	io.archmorph.release-role="bridge" \
	io.archmorph.schema-accepted-revisions="${ARCHMORPH_SCHEMA_ACCEPTED_REVISIONS}" \
	io.archmorph.schema-contract-digest="${ARCHMORPH_SCHEMA_CONTRACT_DIGEST}"

USER root
COPY --chown=appuser:appgroup bridge_overlay/sitecustomize.py /app/sitecustomize.py
COPY --chown=appuser:appgroup bridge_overlay/bridge_entrypoint.py /app/bridge_entrypoint.py
COPY --chown=appuser:appgroup bridge_overlay/bridge_readonly.py /app/bridge_readonly.py
COPY --chown=appuser:appgroup bridge-schema-contract.json /app/release/schema-contract.json
USER appuser

ENV ARCHMORPH_RELEASE_ROLE=bridge
CMD ["gunicorn", "-c", "gunicorn.conf.py", "bridge_entrypoint:app"]
