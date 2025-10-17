from flask import Flask, request, jsonify
import os
import requests
from dotenv import load_dotenv
from dateutil.parser import parse as date_parse
import pytz

# Load environment variables
load_dotenv()
app = Flask(__name__)
CAL_API_KEY = os.getenv("CAL_API_KEY")
CAL_EVENT_TYPE_ID = os.getenv("CAL_EVENT_TYPE_ID")

if not CAL_API_KEY:
    print("⚠️  WARNING: CAL_API_KEY not found in environment variables!")
if not CAL_EVENT_TYPE_ID:
    print("⚠️  WARNING: CAL_EVENT_TYPE_ID not found in environment variables!")


def is_available_slot(dt, timezone="UTC"):
    """Check if the requested time is within availability (Mon-Fri, 9 AM - 5 PM)"""
    tz = pytz.timezone(timezone)
    local_dt = dt.astimezone(tz)

    weekday = local_dt.weekday()  # 0=Monday, 6=Sunday
    hour = local_dt.hour

    # Check if weekend
    if weekday >= 5:  # Saturday or Sunday
        return False, f"Not available on {local_dt.strftime('%A')}"

    # Check if within business hours (9 AM - 5 PM)
    if hour < 9 or hour >= 17:
        return False, f"Outside business hours (9 AM - 5 PM). Requested: {hour}:00"

    return True, "Available"


@app.route("/schedule", methods=["POST"])
def schedule_meeting():
    try:
        data = request.get_json()
        name = data.get("name")
        email = data.get("email")
        time_str = data.get("time")
        duration = data.get("duration", 30)
        user_timezone = data.get("timezone", "UTC")  # Allow client to specify timezone

        if not name or not email or not time_str:
            return jsonify({"error": "Missing required fields: name, email, time"}), 400

        # Parse the date string
        try:
            parsed_date = date_parse(time_str, fuzzy=True)
        except Exception as e:
            print(f"❌ Failed to parse: {time_str}")
            return jsonify({"error": f"Could not parse date: {time_str}"}), 400

        # Ensure timezone awareness (default to UTC if naive)
        if parsed_date.tzinfo is None:
            parsed_date = pytz.UTC.localize(parsed_date)

        # Validate availability
        is_avail, avail_msg = is_available_slot(parsed_date, user_timezone)
        if not is_avail:
            print(f"⏰ Slot unavailable: {avail_msg}")
            return jsonify(
                {
                    "error": "Requested time is not available",
                    "reason": avail_msg,
                    "availability": "Monday-Friday, 9:00 AM - 5:00 PM UTC",
                }
            ), 400

        iso_date = parsed_date.isoformat()
        print(f"✅ Parsed '{time_str}' → {iso_date}")
        print(f"✅ Time slot is available: {avail_msg}")

        # 📅 Call Cal.com API
        payload = {
            "start": iso_date,
            "eventTypeId": int(CAL_EVENT_TYPE_ID),
            "attendee": {
                "name": name,
                "email": email,
                "timeZone": user_timezone,
            },
        }

        headers = {
            "Authorization": f"Bearer {CAL_API_KEY}",
            "Content-Type": "application/json",
            "cal-api-version": "2024-08-13",
        }

        print(f"📤 Sending booking request: {payload}")
        res = requests.post(
            "https://api.cal.com/v2/bookings", json=payload, headers=headers
        )

        booking_data = res.json()

        # Check if request was successful
        if booking_data.get("status") == "success":
            data = booking_data.get("data", {})
            print("✅ Booking created successfully!")
            print(f"   📅 Title: {data.get('title')}")
            print(
                f"   📧 Attendee: {data.get('bookingFieldsResponses', {}).get('name')} ({data.get('bookingFieldsResponses', {}).get('email')})"
            )
            print(f"   🕐 Start: {data.get('start')}")
            print(f"   🕑 End: {data.get('end')}")
            print(f"   ⏱️  Duration: {data.get('duration')} mins")
            print(f"   🔗 Meeting URL: {data.get('meetingUrl')}")
            print(f"   📌 Booking ID: {data.get('id')}")
        elif res.status_code != 200:
            print("❌ Cal.com error:", res.text)
            return jsonify(
                {"error": "Failed to create Cal.com booking", "details": res.text}
            ), 500

        return jsonify(
            {
                "success": True,
                "message": f"Meeting scheduled for {parsed_date}",
                "booking": booking_data,
            }
        ), 200

    except Exception as e:
        print("❌ Exception:", str(e))
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
