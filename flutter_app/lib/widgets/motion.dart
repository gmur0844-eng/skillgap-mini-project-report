import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme/design_system.dart';

/// Motion for Version 2. Two kinds:
///  * motion that answers something (a section arriving, a rule drawing in, a hover): short and finite;
///  * ambient motion (light trails behind the overview, the pulse of a running analysis): continuous, so it runs
///    only in the real application, never when the platform asks for reduced motion and never under the widget-test
///    binding (where it would keep every frame busy); there it shows its still frame.
bool ambientMotion(BuildContext context) =>
    WidgetsBinding.instance is WidgetsFlutterBinding && !(MediaQuery.maybeDisableAnimationsOf(context) ?? false);

/// A status dot that breathes while something is running (a live analysis); a still dot otherwise.
class PulseDot extends StatefulWidget {
  const PulseDot({super.key, required this.color, this.size = 6, this.live = true});
  final Color color;
  final double size;
  final bool live;

  @override
  State<PulseDot> createState() => _PulseDotState();
}

class _PulseDotState extends State<PulseDot> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1600));

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _sync();
  }

  @override
  void didUpdateWidget(covariant PulseDot oldWidget) {
    super.didUpdateWidget(oldWidget);
    _sync();
  }

  void _sync() {
    final run = widget.live && ambientMotion(context);
    if (run && !_c.isAnimating) _c.repeat();
    if (!run && _c.isAnimating) _c.stop();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.size;
    return SizedBox(
      width: s * 2.6,
      height: s * 2.6,
      child: AnimatedBuilder(
        animation: _c,
        builder: (context, _) {
          final t = _c.value;
          return Stack(alignment: Alignment.center, children: [
            if (_c.isAnimating)
              Container(
                width: s + s * 1.6 * t,
                height: s + s * 1.6 * t,
                decoration: BoxDecoration(shape: BoxShape.circle, color: widget.color.withValues(alpha: 0.35 * (1 - t))),
              ),
            Container(width: s, height: s, decoration: BoxDecoration(shape: BoxShape.circle, color: widget.color)),
          ]);
        },
      ),
    );
  }
}

/// A field of slow light trails (the overview's hero band): long curves in the accent and gold, drifting. Static
/// (one still frame) when ambient motion is off.
class LightTrails extends StatefulWidget {
  const LightTrails({super.key, this.count = 22});
  final int count;

  @override
  State<LightTrails> createState() => _LightTrailsState();
}

class _LightTrailsState extends State<LightTrails> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(seconds: 28));

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (ambientMotion(context)) {
      if (!_c.isAnimating) _c.repeat();
    } else {
      _c.stop();
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return RepaintBoundary(
      child: AnimatedBuilder(
        animation: _c,
        builder: (context, _) => CustomPaint(
          painter: _TrailsPainter(
            t: _c.value,
            count: widget.count,
            a: AppColors.primary,
            b: AppColors.accent,
            dark: Design.current.isDark,
          ),
          child: const SizedBox.expand(),
        ),
      ),
    );
  }
}

class _TrailsPainter extends CustomPainter {
  _TrailsPainter({required this.t, required this.count, required this.a, required this.b, required this.dark});
  final double t;
  final int count;
  final Color a, b;
  final bool dark;

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width, h = size.height;
    final phase = t * 2 * math.pi;
    for (var i = 0; i < count; i++) {
      final k = i / count;
      final drift = math.sin(phase + i * 0.7) * h * 0.08;
      final y0 = h * (0.95 - 0.55 * k) + drift;
      final y3 = h * (0.05 + 0.6 * k) - drift * 0.6;
      final path = Path()
        ..moveTo(w * 0.25, y0)
        ..cubicTo(w * (0.45 + 0.1 * math.sin(phase + i)), y0 - h * 0.35, w * (0.7 + 0.08 * math.cos(phase * 0.8 + i)),
            y3 + h * 0.3, w * 1.05, y3);
      final colour = Color.lerp(a, b, k)!;
      final alpha = (dark ? 0.32 : 0.22) * (0.35 + 0.65 * math.sin(math.pi * k).abs());
      final paint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 0.6 + (i % 4) * 0.35
        ..shader = LinearGradient(colors: [colour.withValues(alpha: 0), colour.withValues(alpha: alpha), colour.withValues(alpha: 0)],
                stops: const [0, 0.55, 1])
            .createShader(Offset(w * 0.25, 0) & Size(w * 0.8, h));
      canvas.drawPath(path, paint);
    }
  }

  @override
  bool shouldRepaint(covariant _TrailsPainter old) => old.t != t || old.a != a || old.b != b || old.dark != dark;
}

/// The Version 2 hero band: a rounded panel with the light trails behind its content (the overview's opening).
class HeroBand extends StatelessWidget {
  const HeroBand({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xxl),
      child: Container(
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: AppRadius.card,
          border: Border.all(color: AppColors.border),
        ),
        clipBehavior: Clip.antiAlias,
        child: Stack(children: [
          const Positioned.fill(child: ExcludeSemantics(child: LightTrails())),
          LayoutBuilder(
            builder: (context, box) => Padding(
              padding: EdgeInsets.fromLTRB(box.maxWidth < 600 ? 20 : 40, box.maxWidth < 600 ? 28 : 44,
                  box.maxWidth < 600 ? 20 : 40, box.maxWidth < 600 ? 4 : 8),
              child: child,
            ),
          ),
        ]),
      ),
    );
  }
}

/// A line that draws itself in from the left once (Veloria's rule): finite, so it never keeps a frame busy.
class DrawnRule extends StatelessWidget {
  const DrawnRule({super.key, this.width = 22, this.color});
  final double width;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final reduced = MediaQuery.maybeDisableAnimationsOf(context) ?? false;
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: reduced ? 1 : 0, end: 1),
      duration: const Duration(milliseconds: 900),
      curve: const Cubic(0.2, 0.7, 0.2, 1),
      builder: (context, v, _) => SizedBox(
        width: width,
        height: 1,
        child: Align(
          alignment: Alignment.centerLeft,
          child: Container(width: width * v, height: 1, color: color ?? AppColors.accent),
        ),
      ),
    );
  }
}
