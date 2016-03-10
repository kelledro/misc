#!/usr/bin/python

# This tests the propagation time of new records added to a continually growing zone
# It also tests for propagation by querying against authoratative name servers
# rather than querying the R53 API and checking fon INSYNC status since this a
# better real world test. Propagation is considered complete when all auth nameservers
# respond to the query

import boto3
import time
import datetime
import pytz
import socket
import dns.resolver

zoneId = "Z3JNDBS8LPKXRY"

counter = 0
client = boto3.client('route53')
f = open('proptime.log','w')

while True:
	counter += 1
	hostname = str(counter) + '.testing.com'

	# new record
	upsertResponse = client.change_resource_record_sets(
    		HostedZoneId=zoneId,
    		ChangeBatch={
       		 	'Comment': 'testing update time',
        		'Changes': [
           		 {
               			 'Action': 'UPSERT',
               			 'ResourceRecordSet': {
                   			'Name': hostname,
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

	# Check for record
	resolver = dns.resolver.Resolver()
	resolver.nameservers=[socket.gethostbyname('ns-624.awsdns-14.net')]
	query = resolver.query(hostname, 'A', raise_on_no_answer=False)
	print query.rrset

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

	# write to log
	f.write('Elapsed: ' + str(elapsed) + ' - RequestId: ' + requestId + ' - Submitted: ' + str(submitted) + '\n')
	f.flush()

	time.sleep(30)
