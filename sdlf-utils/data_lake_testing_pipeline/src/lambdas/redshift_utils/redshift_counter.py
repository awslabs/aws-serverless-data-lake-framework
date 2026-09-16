import redshift_core as rs
import time
import sys

## todo: move the json object to s3 instead        
def validation_query():
    return [
        {
            "query":    "select season, \
                            count(*) Cnt, \
                            count(distinct sg.player_id) Players \
                        from pff.nfl_grade_season_grade sg \
                        join pff.nfl_players p on p.id=sg.player_id \
                        group by Season \
                        order by 1;",
            "expected":[
                {"low":2000,"high":2020},
                {"low":2000,"high":40000},
                {"low":200,"high":2020}
            ]
        },
        {
            "query":    "select count(vp.game_id) from \
                        pff.nfl_video_special vp \
                        left join pff.nfl_team_play tp on tp.game_id =vp.game_id\
                        and tp.play_id =vp.play_id \
                        where tp.play_id  is null;",
            "expected":[
                {"low":10,"high":4000}
            ]
        }
    ]

    
def count_records(event, context):
    for i,qry in enumerate(validation_query(), start=1):
        started_at = time.time()
        db_con = connect_redshift('dev','aws-ps-redshift')
        output = db_con.run(qry['query'])
        print("output:" + str( output))
        query_result = output[0]
        print("query_result:" + str(query_result))
        
        for i,o in enumerate(query_result):
            print("column {} expected {} at {}".format(o, str(qry['expected'][i]),i))
            if qry['expected'][i]['low'] <= int(o) <= qry['expected'][i]['high']:
                pass
            else:
                return {"validation_test":"failed"}

    return {"validation_test":"succeeded"}
            
