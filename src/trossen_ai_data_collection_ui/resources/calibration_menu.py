################################################################################
## Form generated from reading UI file 'calibration_menu.ui'
##
## Created by: Qt User Interface Compiler version 6.8.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (
    QCoreApplication,
    QMetaObject,
    QSize,
    Qt,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)


class Ui_calibration_menu:
    def setupUi(self, calibration_menu):
        if not calibration_menu.objectName():
            calibration_menu.setObjectName("calibration_menu")
        calibration_menu.resize(640, 200)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(calibration_menu.sizePolicy().hasHeightForWidth())
        calibration_menu.setSizePolicy(sizePolicy)
        calibration_menu.setMinimumSize(QSize(640, 200))
        calibration_menu.setMaximumSize(QSize(640, 200))
        self.verticalLayout = QVBoxLayout(calibration_menu)
        self.verticalLayout.setObjectName("verticalLayout")
        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.verticalLayout_2 = QVBoxLayout()
        self.verticalLayout_2.setObjectName("verticalLayout_2")
        self.label_2 = QLabel(calibration_menu)
        self.label_2.setObjectName("label_2")
        self.label_2.setAlignment(Qt.AlignCenter)

        self.verticalLayout_2.addWidget(self.label_2)

        self.horizontalLayout_3 = QHBoxLayout()
        self.horizontalLayout_3.setObjectName("horizontalLayout_3")
        self.doubleSpinBox_fl_0 = QDoubleSpinBox(calibration_menu)
        self.doubleSpinBox_fl_0.setObjectName("doubleSpinBox_fl_0")
        self.doubleSpinBox_fl_0.setAlignment(Qt.AlignCenter)
        self.doubleSpinBox_fl_0.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.doubleSpinBox_fl_0.setMinimum(-180.000000000000000)
        self.doubleSpinBox_fl_0.setMaximum(180.000000000000000)
        self.doubleSpinBox_fl_0.setSingleStep(0.100000000000000)

        self.horizontalLayout_3.addWidget(self.doubleSpinBox_fl_0)

        self.doubleSpinBox_fl_1 = QDoubleSpinBox(calibration_menu)
        self.doubleSpinBox_fl_1.setObjectName("doubleSpinBox_fl_1")
        self.doubleSpinBox_fl_1.setAlignment(Qt.AlignCenter)
        self.doubleSpinBox_fl_1.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.doubleSpinBox_fl_1.setMinimum(-180.000000000000000)
        self.doubleSpinBox_fl_1.setMaximum(180.000000000000000)
        self.doubleSpinBox_fl_1.setSingleStep(0.100000000000000)

        self.horizontalLayout_3.addWidget(self.doubleSpinBox_fl_1)

        self.doubleSpinBox_fl_2 = QDoubleSpinBox(calibration_menu)
        self.doubleSpinBox_fl_2.setObjectName("doubleSpinBox_fl_2")
        self.doubleSpinBox_fl_2.setAlignment(Qt.AlignCenter)
        self.doubleSpinBox_fl_2.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.doubleSpinBox_fl_2.setMinimum(-180.000000000000000)
        self.doubleSpinBox_fl_2.setMaximum(180.000000000000000)
        self.doubleSpinBox_fl_2.setSingleStep(0.100000000000000)

        self.horizontalLayout_3.addWidget(self.doubleSpinBox_fl_2)

        self.doubleSpinBox_fl_3 = QDoubleSpinBox(calibration_menu)
        self.doubleSpinBox_fl_3.setObjectName("doubleSpinBox_fl_3")
        self.doubleSpinBox_fl_3.setAlignment(Qt.AlignCenter)
        self.doubleSpinBox_fl_3.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.doubleSpinBox_fl_3.setMinimum(-180.000000000000000)
        self.doubleSpinBox_fl_3.setMaximum(180.000000000000000)
        self.doubleSpinBox_fl_3.setSingleStep(0.100000000000000)

        self.horizontalLayout_3.addWidget(self.doubleSpinBox_fl_3)

        self.doubleSpinBox_fl_4 = QDoubleSpinBox(calibration_menu)
        self.doubleSpinBox_fl_4.setObjectName("doubleSpinBox_fl_4")
        self.doubleSpinBox_fl_4.setAlignment(Qt.AlignCenter)
        self.doubleSpinBox_fl_4.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.doubleSpinBox_fl_4.setMinimum(-180.000000000000000)
        self.doubleSpinBox_fl_4.setMaximum(180.000000000000000)
        self.doubleSpinBox_fl_4.setSingleStep(0.100000000000000)

        self.horizontalLayout_3.addWidget(self.doubleSpinBox_fl_4)

        self.doubleSpinBox_fl_5 = QDoubleSpinBox(calibration_menu)
        self.doubleSpinBox_fl_5.setObjectName("doubleSpinBox_fl_5")
        self.doubleSpinBox_fl_5.setAlignment(Qt.AlignCenter)
        self.doubleSpinBox_fl_5.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.doubleSpinBox_fl_5.setMinimum(-180.000000000000000)
        self.doubleSpinBox_fl_5.setMaximum(180.000000000000000)
        self.doubleSpinBox_fl_5.setSingleStep(0.100000000000000)

        self.horizontalLayout_3.addWidget(self.doubleSpinBox_fl_5)

        self.doubleSpinBox_fl_6 = QDoubleSpinBox(calibration_menu)
        self.doubleSpinBox_fl_6.setObjectName("doubleSpinBox_fl_6")
        self.doubleSpinBox_fl_6.setAlignment(Qt.AlignCenter)
        self.doubleSpinBox_fl_6.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.doubleSpinBox_fl_6.setMinimum(-180.000000000000000)
        self.doubleSpinBox_fl_6.setMaximum(180.000000000000000)
        self.doubleSpinBox_fl_6.setSingleStep(0.100000000000000)

        self.horizontalLayout_3.addWidget(self.doubleSpinBox_fl_6)

        self.verticalLayout_2.addLayout(self.horizontalLayout_3)

        self.label = QLabel(calibration_menu)
        self.label.setObjectName("label")
        self.label.setAlignment(Qt.AlignCenter)

        self.verticalLayout_2.addWidget(self.label)

        self.horizontalLayout_2 = QHBoxLayout()
        self.horizontalLayout_2.setObjectName("horizontalLayout_2")
        self.doubleSpinBox_fr_0 = QDoubleSpinBox(calibration_menu)
        self.doubleSpinBox_fr_0.setObjectName("doubleSpinBox_fr_0")
        self.doubleSpinBox_fr_0.setAlignment(Qt.AlignCenter)
        self.doubleSpinBox_fr_0.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.doubleSpinBox_fr_0.setMinimum(-180.000000000000000)
        self.doubleSpinBox_fr_0.setMaximum(180.000000000000000)
        self.doubleSpinBox_fr_0.setSingleStep(0.100000000000000)

        self.horizontalLayout_2.addWidget(self.doubleSpinBox_fr_0)

        self.doubleSpinBox_fr_1 = QDoubleSpinBox(calibration_menu)
        self.doubleSpinBox_fr_1.setObjectName("doubleSpinBox_fr_1")
        self.doubleSpinBox_fr_1.setAlignment(Qt.AlignCenter)
        self.doubleSpinBox_fr_1.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.doubleSpinBox_fr_1.setMinimum(-180.000000000000000)
        self.doubleSpinBox_fr_1.setMaximum(180.000000000000000)
        self.doubleSpinBox_fr_1.setSingleStep(0.100000000000000)

        self.horizontalLayout_2.addWidget(self.doubleSpinBox_fr_1)

        self.doubleSpinBox_fr_2 = QDoubleSpinBox(calibration_menu)
        self.doubleSpinBox_fr_2.setObjectName("doubleSpinBox_fr_2")
        self.doubleSpinBox_fr_2.setAlignment(Qt.AlignCenter)
        self.doubleSpinBox_fr_2.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.doubleSpinBox_fr_2.setMinimum(-180.000000000000000)
        self.doubleSpinBox_fr_2.setMaximum(180.000000000000000)
        self.doubleSpinBox_fr_2.setSingleStep(0.100000000000000)

        self.horizontalLayout_2.addWidget(self.doubleSpinBox_fr_2)

        self.doubleSpinBox_fr_3 = QDoubleSpinBox(calibration_menu)
        self.doubleSpinBox_fr_3.setObjectName("doubleSpinBox_fr_3")
        self.doubleSpinBox_fr_3.setAlignment(Qt.AlignCenter)
        self.doubleSpinBox_fr_3.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.doubleSpinBox_fr_3.setMinimum(-180.000000000000000)
        self.doubleSpinBox_fr_3.setMaximum(180.000000000000000)
        self.doubleSpinBox_fr_3.setSingleStep(0.100000000000000)

        self.horizontalLayout_2.addWidget(self.doubleSpinBox_fr_3)

        self.doubleSpinBox_fr_4 = QDoubleSpinBox(calibration_menu)
        self.doubleSpinBox_fr_4.setObjectName("doubleSpinBox_fr_4")
        self.doubleSpinBox_fr_4.setAlignment(Qt.AlignCenter)
        self.doubleSpinBox_fr_4.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.doubleSpinBox_fr_4.setMinimum(-180.000000000000000)
        self.doubleSpinBox_fr_4.setMaximum(180.000000000000000)
        self.doubleSpinBox_fr_4.setSingleStep(0.100000000000000)

        self.horizontalLayout_2.addWidget(self.doubleSpinBox_fr_4)

        self.doubleSpinBox_fr_5 = QDoubleSpinBox(calibration_menu)
        self.doubleSpinBox_fr_5.setObjectName("doubleSpinBox_fr_5")
        self.doubleSpinBox_fr_5.setAlignment(Qt.AlignCenter)
        self.doubleSpinBox_fr_5.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.doubleSpinBox_fr_5.setMinimum(-180.000000000000000)
        self.doubleSpinBox_fr_5.setMaximum(180.000000000000000)
        self.doubleSpinBox_fr_5.setSingleStep(0.100000000000000)

        self.horizontalLayout_2.addWidget(self.doubleSpinBox_fr_5)

        self.doubleSpinBox_fr_6 = QDoubleSpinBox(calibration_menu)
        self.doubleSpinBox_fr_6.setObjectName("doubleSpinBox_fr_6")
        self.doubleSpinBox_fr_6.setAlignment(Qt.AlignCenter)
        self.doubleSpinBox_fr_6.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.doubleSpinBox_fr_6.setMinimum(-180.000000000000000)
        self.doubleSpinBox_fr_6.setMaximum(180.000000000000000)
        self.doubleSpinBox_fr_6.setSingleStep(0.100000000000000)

        self.horizontalLayout_2.addWidget(self.doubleSpinBox_fr_6)

        self.verticalLayout_2.addLayout(self.horizontalLayout_2)

        self.horizontalLayout.addLayout(self.verticalLayout_2)

        self.line = QFrame(calibration_menu)
        self.line.setObjectName("line")
        self.line.setFrameShape(QFrame.Shape.VLine)
        self.line.setFrameShadow(QFrame.Shadow.Sunken)

        self.horizontalLayout.addWidget(self.line)

        self.verticalLayout_3 = QVBoxLayout()
        self.verticalLayout_3.setObjectName("verticalLayout_3")
        self.pushButton_teleop = QPushButton(calibration_menu)
        self.pushButton_teleop.setObjectName("pushButton_teleop")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.pushButton_teleop.sizePolicy().hasHeightForWidth())
        self.pushButton_teleop.setSizePolicy(sizePolicy1)

        self.verticalLayout_3.addWidget(self.pushButton_teleop)

        self.pushButton_capture = QPushButton(calibration_menu)
        self.pushButton_capture.setObjectName("pushButton_capture")
        sizePolicy1.setHeightForWidth(self.pushButton_capture.sizePolicy().hasHeightForWidth())
        self.pushButton_capture.setSizePolicy(sizePolicy1)

        self.verticalLayout_3.addWidget(self.pushButton_capture)

        self.line_2 = QFrame(calibration_menu)
        self.line_2.setObjectName("line_2")
        self.line_2.setFrameShape(QFrame.Shape.HLine)
        self.line_2.setFrameShadow(QFrame.Shadow.Sunken)

        self.verticalLayout_3.addWidget(self.line_2)

        self.pushButton_save = QPushButton(calibration_menu)
        self.pushButton_save.setObjectName("pushButton_save")
        sizePolicy1.setHeightForWidth(self.pushButton_save.sizePolicy().hasHeightForWidth())
        self.pushButton_save.setSizePolicy(sizePolicy1)

        self.verticalLayout_3.addWidget(self.pushButton_save)

        self.pushButton_gotopose = QPushButton(calibration_menu)
        self.pushButton_gotopose.setObjectName("pushButton_gotopose")
        sizePolicy1.setHeightForWidth(self.pushButton_gotopose.sizePolicy().hasHeightForWidth())
        self.pushButton_gotopose.setSizePolicy(sizePolicy1)

        self.verticalLayout_3.addWidget(self.pushButton_gotopose)

        self.pushButton_gotohome = QPushButton(calibration_menu)
        self.pushButton_gotohome.setObjectName("pushButton_gotohome")

        self.verticalLayout_3.addWidget(self.pushButton_gotohome)

        self.horizontalLayout.addLayout(self.verticalLayout_3)

        self.verticalLayout.addLayout(self.horizontalLayout)

        self.retranslateUi(calibration_menu)

        QMetaObject.connectSlotsByName(calibration_menu)

    # setupUi

    def retranslateUi(self, calibration_menu):
        calibration_menu.setWindowTitle(
            QCoreApplication.translate("calibration_menu", "Form", None)
        )
        self.label_2.setText(
            QCoreApplication.translate("calibration_menu", "Follower Left Positions (deg)", None)
        )
        self.label.setText(
            QCoreApplication.translate("calibration_menu", "Follower Right Positions (deg)", None)
        )
        self.pushButton_teleop.setText(
            QCoreApplication.translate("calibration_menu", "Manually Pose", None)
        )
        self.pushButton_capture.setText(
            QCoreApplication.translate("calibration_menu", "Capture Positions", None)
        )
        self.pushButton_save.setText(QCoreApplication.translate("calibration_menu", "Save", None))
        self.pushButton_gotopose.setText(
            QCoreApplication.translate("calibration_menu", "Go To Position", None)
        )
        self.pushButton_gotohome.setText(
            QCoreApplication.translate("calibration_menu", "Go To Home", None)
        )

    # retranslateUi
