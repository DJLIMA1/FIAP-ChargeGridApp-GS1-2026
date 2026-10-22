import 'package:flet/flet.dart';
import 'package:flutter/widgets.dart';
import 'package:pointer_interceptor/pointer_interceptor.dart';
import 'vector_map.dart';

class Extension extends FletExtension {
  @override
  Widget? createWidget(Key? key, Control control) {
    if (control.type == 'ChargeGridVectorMap') {
      return VectorMapControl(key: key, control: control);
    }
    if (control.type == 'ChargeGridMapOverlay') {
      return LayoutControl(
        key: key,
        control: control,
        child: PointerInterceptor(
          child: control.buildWidget('content') ?? const SizedBox.shrink(),
        ),
      );
    }
    return null;
  }
}
