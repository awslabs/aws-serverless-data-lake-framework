var AWS = require('aws-sdk');
var md5 = require('md5');

var region = process.env.ES_REGION;
var domain = process.env.ES_ENDPOINT;
var index = 'catalog';
var type = 'object';

exports.handler = async (event, context) => {
    let count = 0;
    for (const record of event.Records) {
        const id = md5(record.dynamodb.Keys.id.S);
        if (record.eventName == 'REMOVE') {
          const document = record.dynamodb.OldImage;
          console.log('Removing document');
          console.log(document);
          await indexDocument(document, 'DELETE', id);
        }
        else {
          const document = record.dynamodb.NewImage;
          console.log('Adding document');
          console.log(document);
          await indexDocument(document, 'PUT', id);
        }
        count += 1;
    }
    return `Successfully processed ${count} records.`;
};


function indexDocument(document, operation, id) {
  var endpoint = new AWS.Endpoint(domain);
  var request = new AWS.HttpRequest(endpoint, region);

  request.method = operation;
  request.path += index + '/' + type + '/' + id;
  request.body = JSON.stringify(document);
  request.headers['host'] = domain;
  request.headers['Content-Type'] = 'application/json';
  // Content-Length is only needed for DELETE requests that include a request
  // body, but including it for all requests doesn't seem to hurt anything.
  request.headers['Content-Length'] = Buffer.byteLength(request.body);

  var credentials = new AWS.EnvironmentCredentials('AWS');
  var signer = new AWS.Signers.V4(request, 'es');
  signer.addAuthorization(credentials, new Date());

  var client = new AWS.HttpClient();
  client.handleRequest(request, null, function(response) {
    console.log(response.statusCode + ' ' + response.statusMessage);
    var responseBody = '';
    response.on('data', function (chunk) {
      responseBody += chunk;
    });
    response.on('end', function (chunk) {
      console.log('Response body: ' + responseBody);
    });
  }, function(error) {
    console.log('Error: ' + error);
  });
}
