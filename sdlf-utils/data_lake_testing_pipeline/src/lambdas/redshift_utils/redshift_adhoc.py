import redshift_core as rs

def adhoc_query(event, context):
    st=time.time()
    db_con = rs.connect_redshift('dev','aws-ps-redshift')
    output = db_con.run(event['query'])
    print("output:" + str(output))
    ed=time.time()
    print("Query {} executed in {} ms.".format(event['query'],((ed-st)*1000)))
