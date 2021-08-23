# get all binaries on installer image
FROM amazonlinux:2 as installer
RUN yum update -y \
  && yum install -y unzip \
  && curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" \
  && unzip awscliv2.zip \
  # The --bin-dir is specified so that we can copy the
  # entire bin directory from the installer stage into
  # into /usr/local/bin of the final stage without
  # accidentally copying over any other executables that
  # may be present in /usr/local/bin of the installer stage.
  && ./aws/install --bin-dir /aws-cli-bin/
COPY unzipping_task.sh /tmp
RUN chmod +x /tmp/unzipping_task.sh

# Copy from installer image to final image
FROM amazonlinux:2
RUN yum update -y \
  && yum install -y gzip\
  && yum clean all
COPY --from=installer /tmp/unzipping_task.sh /tmp/unzipping_task.sh
COPY --from=installer /usr/local/aws-cli/ /usr/local/aws-cli/
COPY --from=installer /aws-cli-bin/ /usr/local/bin/
CMD /tmp/unzipping_task.sh