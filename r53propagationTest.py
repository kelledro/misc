#!/usr/bin/python
import boto3
import time
import datetime
import pytz

client = boto3.client('route53')
f = open('proptime.log','w')
while True:
	time.sleep(30)
	# Make update
	upsertResponse = client.change_resource_record_sets(
    		HostedZoneId='Z1FKJAMHMERS1R',
    		ChangeBatch={
       		 	'Comment': 'testing boto3',
        		'Changes': [
           		 {
               			 'Action': 'UPSERT',
               			 'ResourceRecordSet': {
                   			'Name': 'www.kelledro.com',
               	   			'Type': 'A',
                   			'TTL': 60,
                   			'ResourceRecords': [
                      			{
                          			'Value': '1.1.1.1'
                       			},
                 			]
               			}
			}
			]
		}
	)

	# Get change Status
	getChangeResponse = client.get_change(
		Id=upsertResponse['ChangeInfo']['Id']
	)

	# Wait until change is complete
	while getChangeResponse['ChangeInfo']['Status'] != 'INSYNC':
		time.sleep(0.5)
		# Get Change Status
		getChangeResponse = client.get_change(
         	       Id=upsertResponse['ChangeInfo']['Id']
        	)

	elapsed = datetime.datetime.now(pytz.UTC) - upsertResponse['ChangeInfo']['SubmittedAt']
	requestId = upsertResponse['ResponseMetadata']['RequestId']
	submitted = upsertResponse['ChangeInfo']['SubmittedAt']
	f.write('Elapsed: ' + str(elapsed) + ' -  RequestId: ' + requestId + ' - Submitted: ' + str(submitted) + '\n')
	f.flush()
