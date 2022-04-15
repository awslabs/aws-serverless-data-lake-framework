#!/usr/bin/env bash
set -e
BUCKET=$1
FOLDER="emr-sqoop-bootstrap"
INSTALL_TPT=false
INSTALL_TDCH=false
####
#### /bootstrap /jdbc folders needed in bucket
#### /Upload TDCH to /bootstrap/tdch
####
#FILES="manage_emr_sqoop_shutdown.sh manage_emr_sqoop_shutdown_install.sh run_sqoop.sh"
echo "Creating /var/lib/accumulo path to avoid sqoop warnings"
sudo mkdir /var/lib/accumulo

# ## adding HOSTS /etc/hosts ##
# sudo sh -c 'grep -qxF "10.1.2.3 host1" /etc/hosts || echo "10.1.2.3 host1">>/etc/hosts'

# echo "Finished adding host entry"

#### ADDING SQOOP JDBCS ####
echo "Copying JDBC to sqoop folder"
sudo aws s3 cp s3://"$BUCKET"/"$FOLDER"/jdbc_jars/ /usr/lib/sqoop/lib/ --recursive

if grep isMaster /mnt/var/lib/info/instance.json | grep true;
then
  #### ADDING INITIAL SCRIPTS ####
  echo "Copying Initial scipts to local folder"
  aws s3 cp s3://"$BUCKET"/"$FOLDER"/ /home/hadoop/ --recursive
  sudo chmod -R +x /home/hadoop/
  mkdir -p /home/hadoop/sdlf/sqoop/
  aws secretsmanager list-secrets --filters Key=description,Values=sqoop | grep Name | awk '{print $2}' | sed 's/[",]//g' | while read secret ; do aws secretsmanager get-secret-value --secret-id $secret | jq '.SecretString' |  sed 's/\\"//g' | sed 's/"{//g' | sed 's/}"//g' | awk '{split($0,a,"password:"); printf a[2]}' > /home/hadoop/$secret ; done
  sudo chown hadoop:hadoop -R /home/hadoop/sdlf/sqoop

  ## TDCH installation ##
  if [ "$INSTALL_TDCH" = true ] ;
  then
    echo "Installing TDCH"
    sudo aws s3 cp s3://"$BUCKET"/"$FOLDER"/tdch/ /tmp --recursive
    #rpm -ivh /tmp/teradata-connector-1.7.3-hadoop3.x.noarch.rpm
    sudo rpm -ivh /tmp/teradata-connector-*.noarch.rpm
    #teradata jdbc#
    sudo cp /usr/lib/tdch/*/lib/*.jar /usr/lib/sqoop/lib/

    ###SESSION######
    #.bash_profile
    #### VERIFY THE RIGHT PROFILE, .bashrc or -bash_profile
    sudo sh -c 'echo "export HIVE_HOME=/usr/lib/hive" >> /home/hadoop/.bashrc'
    sudo sh -c 'echo "export HADOOP_HOME=/usr/lib/hadoop" >> /home/hadoop/.bashrc'
    sudo sh -c 'echo "export TDCH_JAR=/usr/lib/tdch/1.7/lib/teradata-connector-1.7.3.jar" >> /home/hadoop/.bashrc'
    sudo sh -c 'echo "export LIB_JARS=$HIVE_HOME/lib/antlr-runtime-3.5.2.jar,$HIVE_HOME/lib/commons-pool-1.5.4.jar,$HIVE_HOME/lib/commons-dbcp-1.4.jar,$HIVE_HOME/lib/libthrift-0.9.3.jar,$HIVE_HOME/lib/libfb303-0.9.3.jar,$HIVE_HOME/lib/jdo-api-3.0.1.jar,$HIVE_HOME/lib/datanucleus-rdbms-4.1.19.jar,$HIVE_HOME/lib/datanucleus-core-4.1.17.jar,$HIVE_HOME/lib/datanucleus-api-jdo-4.2.4.jar,$HIVE_HOME/lib/commons-pool2-2.2.jar,$HIVE_HOME/lib/commons-dbcp2-2.0.1.jar,$HIVE_HOME/lib/hive-metastore-2.3.6-amzn-2.jar,$HIVE_HOME/lib/hive-exec-2.3.6-amzn-2.jar,$HIVE_HOME/lib/hive-jdbc-2.3.6-amzn-2.jar,$HIVE_HOME/lib/hive-cli-2.3.6-amzn-2.jar,$HIVE_HOME/lib/hive-jdbc-handler-2.3.6-amzn-2.jar" >> /home/hadoop/.bashrc'
    sudo sh -c 'echo "export HADOOP_CLASSPATH=$HIVE_HOME/lib/antlr-runtime-3.5.2.jar:$HIVE_HOME/lib/commons-pool-1.5.4.jar:$HIVE_HOME/lib/commons-dbcp-1.4.jar:$HIVE_HOME/lib/libthrift-0.9.3.jar:$HIVE_HOME/lib/libfb303-0.9.3.jar:$HIVE_HOME/lib/jdo-api-3.0.1.jar:$HIVE_HOME/lib/datanucleus-rdbms-4.1.19.jar:$HIVE_HOME/lib/datanucleus-core-4.1.17.jar:$HIVE_HOME/lib/datanucleus-api-jdo-4.2.4.jar:$HIVE_HOME/lib/commons-pool2-2.2.jar:$HIVE_HOME/lib/commons-dbcp2-2.0.1.jar:$HIVE_HOME/lib/hive-metastore-2.3.6-amzn-2.jar:$HIVE_HOME/lib/hive-exec-2.3.6-amzn-2.jar:$HIVE_HOME/lib/hive-jdbc-2.3.6-amzn-2.jar:$HIVE_HOME/lib/hive-cli-2.3.6-amzn-2.jar:$HIVE_HOME/lib/hive-jdbc-handler-2.3.6-amzn-2.jar" >> /home/hadoop/.bashrc'

  fi

  #### TPT ####
  if [ "$INSTALL_TPT" = true ] ;
  then
    echo "Installing TPT"
    sudo aws s3 cp s3://"$BUCKET"/"$FOLDER"/tpt/ /tmp --recursive
    sudo tar -xvf /tmp/TeradataToolsAndUtilitiesBase__linux_* -C /tmp
    sudo /tmp/TeradataToolsAndUtilitiesBase/setup.bat a
  fi

  ### spark
  #execute spark shell with user different from hadoop user.
  sudo chmod 444 /var/aws/emr/userData.json

  echo "Changing downloaded files owner to hadoop user"
  sudo chown hadoop:hadoop -R /home/hadoop
  nohup sh /home/hadoop/get_secrets.sh &
fi

