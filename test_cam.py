import cv2
import time

for index in range(5):

    print("\n" + "=" * 50)
    print(f"TESTING INDEX {index}")
    print("=" * 50)

    cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)

    if not cap.isOpened():
        print("❌ Cannot open")
        continue

    print("Opened:", True)

    # IMPORTANT: Try MJPEG
    cap.set(
        cv2.CAP_PROP_FOURCC,
        cv2.VideoWriter_fourcc(*"MJPG")
    )

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    time.sleep(1)

    print(
        "Resolution:",
        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "x",
        int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    )

    print(
        "FPS:",
        cap.get(cv2.CAP_PROP_FPS)
    )

    success = False

    for attempt in range(30):

        ret, frame = cap.read()

        if ret and frame is not None:

            print(
                f"✅ FRAME SUCCESS on attempt {attempt + 1}"
            )

            cv2.imshow(
                f"Camera Index {index}",
                frame
            )

            success = True

            # Keep displaying this camera
            start = time.time()

            while time.time() - start < 3:
                ret, frame = cap.read()

                if ret and frame is not None:
                    cv2.imshow(
                        f"Camera Index {index}",
                        frame
                    )

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    cap.release()
                    cv2.destroyAllWindows()
                    raise SystemExit

            break

        else:
            print(
                f"❌ No frame - attempt {attempt + 1}"
            )

        time.sleep(0.1)

    if not success:
        print(
            f"❌ INDEX {index} OPENED BUT PRODUCED NO FRAME"
        )

    cap.release()
    cv2.destroyAllWindows()


print("\nDONE")