import cv2
import numpy as np
import requests

VIDEO_PATH = "seed_video_falling.mp4"

API_URL = "http://127.0.0.1:5000/api/seed_event"
TUBE_ID = 1

MIN_AREA = 60
MAX_AREA = 2000
DETECTION_LINE_Y = 350

LOWER_GREEN = np.array([40, 120, 80])
UPPER_GREEN = np.array([80, 255, 255])

cap = cv2.VideoCapture(VIDEO_PATH)

green_count = 0
counted_ids = set()

while True:

    ret, frame = cap.read()

    if not ret:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        continue

    blurred = cv2.GaussianBlur(frame, (5, 5), 0)
    hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)

    mask = cv2.inRange(hsv, LOWER_GREEN, UPPER_GREEN)

    kernel = np.ones((3, 3), np.uint8)

    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for cnt in contours:

        area = cv2.contourArea(cnt)

        if area < MIN_AREA or area > MAX_AREA:
            continue

        x, y, w, h = cv2.boundingRect(cnt)

        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

        if y < DETECTION_LINE_Y < y + h:

            blob_id = (x, y, w, h)

            if blob_id not in counted_ids:

                green_count += 1
                counted_ids.add(blob_id)

                raw_event = {
                    "tube_id": TUBE_ID,
                    "seed_count": 1
                }

                try:
                    requests.post(API_URL, json=raw_event)
                except:
                    pass

    cv2.line(frame, (0, DETECTION_LINE_Y),
             (frame.shape[1], DETECTION_LINE_Y),
             (255, 0, 0), 2)

    cv2.putText(frame,
                f"Green Seeds: {green_count}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 0),
                2)

    cv2.imshow("Green Seed Detection", frame)
    cv2.imshow("Mask", mask)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()