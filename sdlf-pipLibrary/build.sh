#!/bin/bash 

team_name=$1

for dir in ./*/
do
    dir=${dir%*/}      # remove the trailing "/"
    echo ${dir##*/}    # print everything after the final "/"
    echo "---- Looking to move to: "
    cd $dir
    echo "Moving into dir..."
    echo "Current directory contents:"
    ls
    if [ -f "./requirements.txt" ]; then
        echo "requirements.txt exists"
        echo "-----> making temporary directory"
        mkdir -p layer/python
        pip3 -q install -r ./requirements.txt -t layer/python
        cd layer/
        zip -r layer.zip python/ -x \*__pycache__\*
        dir_name=$(echo "${dir//.\/}")
        echo "Uploading Lambda Layer as sdlf-$team_name-$dir_name..."
        
        set +e
        layer=$(aws lambda publish-layer-version --layer-name sdlf-$team_name-$dir_name --description "Contains the libraries specified in requirements.txt" --compatible-runtimes "python3.6" "python3.7" --zip-file fileb://./layer.zip)
        status=$?
        set -e

        if [ $status -ne 0 ] ; then
            exit $status
        fi
        
        latest_layer_version=$(echo $layer | jq -r .LayerVersionArn)
        paramname=$(printf '/SDLF/Lambda/%s/%s' $team_name $dir_name)
        aws ssm put-parameter --name $paramname --value $latest_layer_version --type String --overwrite
        cd ../..
    elif [ -f "./external_layers.json" ]; then
        echo "external_layers.json exists"
        artifacts_bucket=$(aws ssm get-parameter --name /SDLF/S3/ArtifactsBucket | grep -o -E "\"Value\": \"[a-z0-9|-]+\"" | awk -F\: '{print $2}' | sed 's/.$//')
        python3 ../external_layers.py ${artifacts_bucket:2} $team_name
        cd ../
    fi
    echo "============= COMPLETED DIRECTORY BUILD ============="
done