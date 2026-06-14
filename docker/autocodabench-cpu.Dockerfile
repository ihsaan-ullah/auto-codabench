# autocodabench CPU base image.
#
# Starts from the Codabench-hosted CPU worker image (Python 3.12) and adds the
# essential scientific-Python stack plus a pinned starting-kit notebook
# toolchain, so generated competition bundles run inside the same image
# Codabench's worker uses — with no per-run installation. The Codabench worker
# executes programs INSIDE the competition's docker_image and never installs
# requirements.txt; pre-baking the dependencies here is what makes a clean
# local run evidence that the bundle will execute on the platform.
#
# Build and push with docker/build_and_push.sh (which sets the registry
# namespace and tag). See docker/README.md.
FROM codalab/codalab-legacy:py312

LABEL org.opencontainers.image.title="autocodabench-base-cpu"
LABEL org.opencontainers.image.description="Codabench py312 worker image plus the autocodabench essential CPU stack."
LABEL org.opencontainers.image.source="https://github.com/ihsaan-ullah/auto-codabench"

# Install the shared essential stack. Copy only the requirements file first so
# this layer is cached across rebuilds that do not change the dependency set.
COPY autocodabench-base-requirements.txt /tmp/autocodabench-base-requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
 && python -m pip install --no-cache-dir -r /tmp/autocodabench-base-requirements.txt \
 && rm -f /tmp/autocodabench-base-requirements.txt

# Fail the build if the notebook toolchain cannot satisfy the runner's exact
# invocation, so a broken pin never ships silently. We do not merely check
# `--help`: we author a one-cell notebook and run it through the same command
# the starting-kit runner uses (`jupyter nbconvert --to notebook --execute
# --inplace`), which exercises nbconvert -> nbclient -> ipykernel end to end.
RUN python -c "import numpy, pandas, sklearn, scipy, matplotlib, seaborn, PIL; \
print('autocodabench-base-cpu: stack import OK')" \
 && python -c "import json; json.dump({'cells':[{'cell_type':'code','metadata':{},'source':['print(1+1)'],'outputs':[],'execution_count':None}],'metadata':{'kernelspec':{'name':'python3','display_name':'Python 3'},'language_info':{'name':'python'}},'nbformat':4,'nbformat_minor':5}, open('/tmp/smoke.ipynb','w'))" \
 && jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=-1 /tmp/smoke.ipynb \
 && rm -f /tmp/smoke.ipynb \
 && echo "autocodabench-base-cpu: notebook toolchain OK"
