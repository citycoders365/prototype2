import os
os.environ["YOLO_VERBOSE"] = "False"
os.environ["ULTRALYTICS_VERBOSE"] = "False"
import sys
import cv2
import json
from ultralytics import YOLO
from ultralytics.utils import LOGGER
import logging
LOGGER.setLevel(logging.CRITICAL)

def analyze_bus_image(image_path):
    print("Loading YOLOv8 nano model...", flush=True)
    model = YOLO("yolov8n.pt", verbose=False)
    
    print(f"Opening image: {image_path}", flush=True)
    img = cv2.imread(image_path)
    
    if img is None:
        print(f"Error: Could not read image at {image_path}. Make sure the file exists!", flush=True)
        return

    print("Running inference...", flush=True)
    results = model(img, classes=[0], conf=0.3, verbose=False)
    
    standing_count = 0
    total_people = 0
    
    # Process results
    for result in results:
        boxes = result.boxes
        for box in boxes:
            total_people += 1
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
            
            height = y2 - y1
            width = x2 - x1
            aspect_ratio = height / width
            
            # Stricter heuristic: Box must be 2.25x taller than wide
            is_standing = aspect_ratio > 2.25
            
            if is_standing:
                standing_count += 1
                
            # Draw bounding boxes and text
            color = (0, 0, 255) if is_standing else (0, 255, 0) # Red for standing, Green for sitting
            label = "Standing" if is_standing else "Sitting"
            cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
            cv2.putText(img, label, (int(x1), int(y1) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    annotated_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_annotated.jpg")
    cv2.imwrite(annotated_path, img)
    
    # Display the result on the screen
    print(f"Displaying annotated image. Press any key in the image window to close it...", flush=True)
    cv2.imshow("Annotated Output", img)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    result = {
        "total": total_people,
        "standing": standing_count,
        "sitting": total_people - standing_count
    }

    result_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2)

    print("Done! Results written to results.json", flush=True)

if __name__ == "__main__":
    # Look for bus_test.jpg in the same directory as this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    img_path = os.path.join(script_dir, 'bus_test.jpg')
    
    analyze_bus_image(img_path)
    # Read results back from JSON and print clearly
    result_path = os.path.join(script_dir, 'results.json')
    r = json.load(open(result_path))
    sys.stdout.write("\nRESULT: total=%d standing=%d sitting=%d\n" % (r['total'], r['standing'], r['sitting']))
    sys.stdout.flush()