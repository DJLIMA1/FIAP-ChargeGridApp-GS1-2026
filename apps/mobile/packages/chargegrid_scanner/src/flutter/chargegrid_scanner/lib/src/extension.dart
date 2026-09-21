import 'package:flet/flet.dart';
import 'package:flutter/widgets.dart';

import 'qr_scanner.dart';

class Extension extends FletExtension {
  @override
  Widget? createWidget(Key? key, Control control) {
    if (control.type == 'ChargeGridQRScanner') {
      return QRScannerControl(key: key, control: control);
    }
    return null;
  }
}
