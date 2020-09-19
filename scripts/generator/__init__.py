import datetime
import json
import time
import sys


import arrow  # type: ignore
import stravalib  # type: ignore
from sqlalchemy import func
from gpxtrackposter import track_loader

from .db import init_db, update_or_create_activity,Activity


class Generator:
    def __init__(self, db_path, client_id, client_secret, refresh_token):
        self.client = stravalib.Client()
        self.session = init_db(db_path)

        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token


    def check_access(self) -> None:
        now = datetime.datetime.fromtimestamp(time.time())
        response = self.client.refresh_access_token(
            client_id=self.client_id, client_secret=self.client_secret, refresh_token=self.refresh_token,
        )
        # Update the authdata object
        self.access_token = response["access_token"]
        self.refresh_token = response["refresh_token"]
        self.expires_at = datetime.datetime.fromtimestamp(response["expires_at"])

        self.client.access_token = response["access_token"]
        print("Access ok")

    def sync(self, force: bool = False):
        self.check_access()

        print("Start syncing")
        if force:
            filters = {"before": datetime.datetime.utcnow()}
        else:
            last_activity = self.session.query(func.max(Activity.start_date)).scalar()
            if last_activity:
                last_activity_date = arrow.get(last_activity)
                last_activity_date = last_activity_date.shift(days=-7)
                filters = {"after": last_activity_date.datetime}
            else:
                filters = {"before": datetime.datetime.utcnow()}

        for run_activity in self.client.get_activities(**filters):
            created = update_or_create_activity(self.session, run_activity)
            if created:
                sys.stdout.write("+")
            else:
                sys.stdout.write(".")
            sys.stdout.flush()

        self.session.commit()

    def sync_from_gpx(self, gpx_dir, force=False):
        loader = track_loader.TrackLoader()
        tracks = loader.load_tracks(gpx_dir)
        if not tracks:
            print("No tracks found.")
            return
        for t in tracks:
            created = update_or_create_activity(self.session, t.to_namedtuple())
            if created:
                sys.stdout.write("+")
            else:
                sys.stdout.write(".")
            sys.stdout.flush()

        self.session.commit()
            

    def load(self):
        activities = self.session.query(Activity).order_by(Activity.start_date_local)
        activity_list = []

        streak = 0
        last_date = None
        for activity in activities:
            # Determine running streak.
            if activity.type == "Run":
                date = datetime.datetime.strptime(activity.start_date_local, "%Y-%m-%d %H:%M:%S").date()
                if last_date is None:
                    streak = 1
                elif date == last_date:
                    pass
                elif date == last_date + datetime.timedelta(days=1):
                    streak += 1
                else:
                    assert date > last_date
                    streak = 1
                activity.streak = streak
                last_date = date
                activity_list.append(activity.to_dict())

        return activity_list
