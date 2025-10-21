from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import requests
from dotenv import load_dotenv
from dateutil.parser import parse as date_parse
import pytz

# Load environment variables
load_dotenv()
app = Flask(__name__)

CORS(app)

CAL_API_KEY = os.getenv("CAL_API_KEY")
CAL_EVENT_TYPE_ID = os.getenv("CAL_EVENT_TYPE_ID")
MCP_SECRET = os.getenv("MCP_SECRET")  # Optional security header

if not CAL_API_KEY:
    print("⚠️  WARNING: CAL_API_KEY not found in environment variables!")
if not CAL_EVENT_TYPE_ID:
    print("⚠️  WARNING: CAL_EVENT_TYPE_ID not found in environment variables!")


# 🧠 Availability checker
def is_available_slot(dt, timezone="UTC"):
    tz = pytz.timezone(timezone)
    local_dt = dt.astimezone(tz)

    weekday = local_dt.weekday()  # 0=Monday, 6=Sunday
    hour = local_dt.hour

    if weekday >= 5:
        return False, f"Not available on {local_dt.strftime('%A')}"
    if hour < 9 or hour >= 17:
        return False, f"Outside business hours (9 AM - 5 PM). Requested: {hour}:00"

    return True, "Available"


# 🧩 Root endpoint — defines MCP tools available
@app.route("/", methods=["GET"])
def mcp_root():
    return jsonify(
        {
            "mcp": "1.0",
            "tools": [
                {
                    "name": "schedule_meeting",
                    "description": "Schedules a meeting in Cal.com using a name, email, and natural language date.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Full name of attendee",
                            },
                            "email": {
                                "type": "string",
                                "description": "Email of attendee",
                            },
                            "time": {
                                "type": "string",
                                "description": "Natural language time (e.g., 'next Monday at 3pm')",
                            },
                            "duration": {
                                "type": "integer",
                                "description": "Meeting duration in minutes",
                                "default": 30,
                            },
                            "timezone": {
                                "type": "string",
                                "description": "Timezone (e.g., 'Europe/Amsterdam', 'Europe/Kyiv', 'America/New_York'). MUST match your Cal.com account timezone setting.",
                                "default": "Europe/Amsterdam",
                            },
                        },
                        "required": ["name", "email", "time"],
                    },
                }
            ],
        }
    )


@app.route("/tools", methods=["GET"])
def list_tools():
    return jsonify(
        {
            "tools": [
                {
                    "name": "schedule_meeting",
                    "description": "Schedules a call on Cal.com given a name, email, and time string.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Full name of the attendee",
                            },
                            "email": {
                                "type": "string",
                                "description": "Email address of the attendee",
                            },
                            "time": {
                                "type": "string",
                                "description": "Natural language date/time (e.g. 'next Monday at 3pm')",
                            },
                            "timezone": {
                                "type": "string",
                                "description": "Timezone (e.g., 'Europe/Kyiv', 'America/New_York')",
                            },
                        },
                        "required": ["name", "email", "time"],
                    },
                }
            ]
        }
    )


# 🧩 MCP Tool Endpoint
@app.route("/tools/schedule_meeting", methods=["POST"])
def schedule_meeting_tool():
    # Optional header security check
    # if MCP_SECRET and request.headers.get("X-MCP-SECRET") != MCP_SECRET:
    #     return jsonify({"error": "Unauthorized"}), 401

    try:
        data = request.get_json()
        name = data.get("name")
        email = data.get("email")
        time_str = data.get("time")
        duration = data.get("duration", 30)
        user_timezone = data.get("timezone", "Europe/Amsterdam")

        if not name or not email or not time_str:
            return jsonify({"error": "Missing required fields: name, email, time"}), 400

        # Validate timezone
        try:
            tz = pytz.timezone(user_timezone)
        except pytz.exceptions.UnknownTimeZoneError:
            return jsonify({"error": f"Invalid timezone: {user_timezone}"}), 400

        # Parse date/time in the user's timezone
        try:
            parsed_date = date_parse(time_str, fuzzy=True)
            
            # If no timezone info, assume it's in the user's timezone
            if parsed_date.tzinfo is None:
                parsed_date = tz.localize(parsed_date)
            else:
                # Convert to user's timezone for consistency
                parsed_date = parsed_date.astimezone(tz)
                
        except Exception as e:
            return jsonify({"error": f"Could not parse date: {time_str}", "details": str(e)}), 400

        # Validate slot availability
        is_avail, avail_msg = is_available_slot(parsed_date, user_timezone)
        if not is_avail:
            return jsonify(
                {
                    "error": "Requested time is not available",
                    "reason": avail_msg,
                    "availability": "Monday-Friday, 9:00 AM - 5:00 PM in your timezone",
                }
            ), 400

        # Convert to UTC for Cal.com API
        iso_date = parsed_date.astimezone(pytz.UTC).isoformat()

        # Call Cal.com API
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

        res = requests.post(
            "https://api.cal.com/v2/bookings", json=payload, headers=headers
        )
        booking_data = res.json()

        print("***********", booking_data)
        print("################", booking_data.get("status"))
        print("##&&&&&&&&&&&&&&#", booking_data.get("status") == "success")
        print(f"Response Status Code: {res.status_code}")
        print(f"Response Status: {booking_data.get('status')}")

        if res.status_code != 201 or booking_data.get("status") != "success":
            return jsonify(
                {"error": "Failed to create Cal.com booking", "details": booking_data}
            ), 500

        return jsonify(
            {
                "success": True,
                "message": f"Meeting scheduled for {iso_date}",
                "booking": booking_data.get("data"),
            }
        )

    except Exception as e:
        print("❌ Exception:", str(e))
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500


# 🔧 Health check (optional)
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True)