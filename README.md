# 🪑 Vision-Based Chair Seat Inspection System

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![OpenCV](https://img.shields.io/badge/OpenCV-4.8%2B-green)](https://opencv.org/)

An automated quality-control solution designed for chair manufacturing lines. This system replaces manual visual inspection by using computer vision to verify that staples are correctly placed in all critical locations across five different viewpoints.

## 🌟 Key Features

- **Multi-View Inspection**: Analyzes images from five angles: Top, Front, Back, Left, and Right.
- **Staple Round Detection**: Automatically detects staple rounds in the top view using contour analysis.
- **16-Point Verification**: Ensures all 16 predefined critical staple points are present.
- **Side View Analysis**: Uses Regions of Interest (ROIs) to verify staple presence on the sides of the chair.
- **Visual Reporting**: Generates annotated images highlighting detected staples (blue/yellow) and failed regions (red).
- **Detailed Console Reports**: Provides a clear PASS/FAIL breakdown for every check.

---

## 🚀 Getting Started


## 🔄 Inspection Workflow

```text
        SELECT CHAIR RECIPE
                ↓
       CHECK CAMERA STATUS
                ↓
      CHECK FIXTURE POSITION
                ↓
       CAPTURE BACK + FRONT
                ↓
        ROTATE FIXTURE 90°
                ↓
       CAPTURE RIGHT + LEFT
                ↓
        APPLY CALIBRATION
                ↓
        DETECT STAPLES
                ↓
    VALIDATE INSPECTION REGIONS
                ↓
       GENERATE RESULTS
                ↓
          PASS / FAIL
                ↓
       RESULT + QR LABEL
```

### Prerequisites
- **Python**: 3.9 to 3.12 (Tested on 3.11)
- **OS**: Linux (Ubuntu), macOS, or Windows 10/11
- **Hardware**: Standard PC or Raspberry Pi (for production GPIO control)

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/parshva7/vision-based-chair-seat-inspection.git
   cd vision-based-chair-seat-inspection
   ```

2. **Create a virtual environment** (Recommended):
   ```bash
   python3 -m venv venv
   # Activate on macOS/Linux:
   source venv/bin/activate
   # Activate on Windows:
   venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

### Preparing Your Images
Place your chair images in the `images/` folder using these exact filenames:
- `top.jpg`
- `front.jpg`
- `back.jpg`
- `left.jpg`
- `right.jpg`

*(Note: If you only have one image for testing, name it `test_chair.jpg` and the system will use it as a fallback for missing views.)*

---

## 🛠 Usage

### Running the Inspection
To start the automated inspection process, run:
```bash
python src/main.py
```

**What happens next?**
1. The system loads the images from the `images/` folder.
2. It performs top-view border and 16-point analysis.
3. It inspects the four side views using predefined ROI models.
4. It calculates a final **PASS/FAIL** decision.
5. **Results** are saved as annotated images in the `outputs/` folder.

### Calibration (For New Chair Models)
If you change the chair model or camera position, you must re-calibrate the system using the provided scripts:

1. **16-Point Calibration**: `python src/calibrate_16_points.py` (Click 16 staple locations on the top view).
2. **Border Calibration**: `python src/calibrate_border_region.py` (Define the outer staple border).
3. **Side Point Calibration**: `python src/calibrate_side_points.py` (Define critical points for side views).

---

## 📂 Project Structure

```text
├── images/             # Input images (top, front, back, left, right)
├── models/             # JSON calibration files (ROIs and points)
├── outputs/            # Annotated result images
├── src/                # Core logic
│   ├── main.py         # Main orchestrator
│   ├── analyze_border.py   # Top view staple round detection
│   ├── detect_staples_2.py # Core staple detection algorithm
│   └── inspect_side_views.py # Side view ROI analysis
├── requirements.txt    # Python dependencies
└── PROJECT_DOCUMENTATION.md # Detailed technical specifications
```

## ⚙️ Configuration
The system is driven by JSON files in the `models/` directory:
- `border_regions.json`: Defines the outer boundary and 16-point coordinates.
- `side_points.json`: Defines critical points for side views.

---
# 👨‍💻 Author

**Parshva Panchal**

- GitHub: https://github.com/parshva7
- LinkedIn: https://linkedin.com/in/parshvap1

---

<div align="center">

⭐ If you found this project useful, please consider giving it a star.

<div align="center">

![GitHub Repo stars](https://img.shields.io/github/stars/parshva7/Online-Learning-Platform?style=for-the-badge)
![GitHub forks](https://img.shields.io/github/forks/parshva7/Online-Learning-Platform?style=for-the-badge)
![GitHub last commit](https://img.shields.io/github/last-commit/parshva7/Online-Learning-Platform?style=for-the-badge)
![GitHub issues](https://img.shields.io/github/issues/parshva7/Online-Learning-Platform?style=for-the-badge)

</div>
---
## 📝 License
This project is developed for quality control in manufacturing. Please refer to `PROJECT_DOCUMENTATION.md` for further technical details.
