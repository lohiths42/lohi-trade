package com.lohitrade.ui.onboarding

import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.lohitrade.data.onboarding.OnboardingService
import com.lohitrade.data.onboarding.TooltipPosition
import com.lohitrade.data.onboarding.WalkthroughSteps

/**
 * 7-step guided walkthrough overlay with spotlight effect, tooltips,
 * and Next/Back/Skip navigation (Req 33.2, 33.3, 33.5, 33.8).
 *
 * Uses Jetpack Compose animations: animateFloatAsState, AnimatedVisibility,
 * animateContentSize, spring/tween specs.
 */
@Composable
fun WalkthroughOverlay(
    onboardingService: OnboardingService,
    modifier: Modifier = Modifier
) {
    val showWalkthrough by onboardingService.showWalkthrough.collectAsState()
    val currentStep by onboardingService.currentStep.collectAsState()

    AnimatedVisibility(
        visible = showWalkthrough,
        enter = fadeIn(animationSpec = tween(300)),
        exit = fadeOut(animationSpec = tween(300))
    ) {
        WalkthroughContent(
            currentStep = currentStep,
            onNext = { onboardingService.nextStep() },
            onBack = { onboardingService.previousStep() },
            onSkip = { onboardingService.skipOnboarding() },
            modifier = modifier
        )
    }
}

@Composable
private fun WalkthroughContent(
    currentStep: Int,
    onNext: () -> Unit,
    onBack: () -> Unit,
    onSkip: () -> Unit,
    modifier: Modifier = Modifier
) {
    val step = WalkthroughSteps.all[currentStep]
    val isLastStep = currentStep == WalkthroughSteps.totalSteps - 1

    // Spotlight dimmed overlay (Req 33.3)
    val overlayAlpha by animateFloatAsState(
        targetValue = 0.6f,
        animationSpec = tween(300),
        label = "overlayAlpha"
    )

    // Tooltip card animation
    val cardScale by animateFloatAsState(
        targetValue = 1f,
        animationSpec = spring(dampingRatio = 0.8f, stiffness = Spring.StiffnessMediumLow),
        label = "cardScale"
    )

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(Color.Black.copy(alpha = overlayAlpha))
            .clickable(
                indication = null,
                interactionSource = remember { MutableInteractionSource() }
            ) { /* Block taps on background */ }
    ) {
        Column(
            modifier = Modifier.fillMaxSize(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            Spacer(modifier = Modifier.weight(1f))

            // Tooltip card with step content
            AnimatedContent(
                targetState = currentStep,
                transitionSpec = {
                    (fadeIn(tween(250)) + scaleIn(
                        initialScale = 0.95f,
                        animationSpec = tween(250)
                    )).togetherWith(
                        fadeOut(tween(200)) + scaleOut(
                            targetScale = 0.95f,
                            animationSpec = tween(200)
                        )
                    )
                },
                label = "stepTransition"
            ) { stepIndex ->
                val animStep = WalkthroughSteps.all[stepIndex]
                TooltipCard(
                    step = animStep,
                    modifier = Modifier
                        .padding(horizontal = 24.dp)
                        .graphicsLayer { scaleX = cardScale; scaleY = cardScale }
                )
            }

            Spacer(modifier = Modifier.weight(1f))

            // Navigation bar
            NavigationBar(
                currentStep = currentStep,
                isLastStep = isLastStep,
                onNext = onNext,
                onBack = onBack,
                onSkip = onSkip,
                modifier = Modifier
                    .padding(horizontal = 24.dp)
                    .padding(bottom = 32.dp)
            )
        }
    }
}

@Composable
private fun TooltipCard(
    step: com.lohitrade.data.onboarding.WalkthroughStep,
    modifier: Modifier = Modifier
) {
    // Animated pointer bounce
    val infiniteTransition = rememberInfiniteTransition(label = "pointerBounce")
    val pointerOffset by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = -8f,
        animationSpec = infiniteRepeatable(
            animation = tween(1000, easing = EaseInOut),
            repeatMode = RepeatMode.Reverse
        ),
        label = "pointerOffset"
    )

    Card(
        modifier = modifier
            .shadow(12.dp, RoundedCornerShape(16.dp)),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface
        )
    ) {
        Column(
            modifier = Modifier.padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            // Animated pointer arrow
            Icon(
                imageVector = arrowIcon(step.tooltipPosition),
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier
                    .size(24.dp)
                    .graphicsLayer { translationY = pointerOffset }
            )

            Spacer(modifier = Modifier.height(12.dp))

            // Step icon
            Icon(
                imageVector = stepIcon(step.iconName),
                contentDescription = step.title,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(48.dp)
            )

            Spacer(modifier = Modifier.height(16.dp))

            // Title
            Text(
                text = step.title,
                style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Bold),
                textAlign = TextAlign.Center
            )

            Spacer(modifier = Modifier.height(8.dp))

            // Description
            Text(
                text = step.description,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center
            )
        }
    }
}

@Composable
private fun NavigationBar(
    currentStep: Int,
    isLastStep: Boolean,
    onNext: () -> Unit,
    onBack: () -> Unit,
    onSkip: () -> Unit,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        // Progress indicator (Req 33.5)
        ProgressIndicator(currentStep = currentStep)

        Spacer(modifier = Modifier.height(16.dp))

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            // Back or Skip button
            if (currentStep > 0) {
                TextButton(onClick = onBack) {
                    Icon(
                        Icons.Default.ChevronLeft,
                        contentDescription = "Back",
                        modifier = Modifier.size(18.dp)
                    )
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("Back")
                }
            } else {
                TextButton(onClick = onSkip) {
                    Text("Skip")
                }
            }

            // Step counter
            Text(
                text = "Step ${currentStep + 1} of ${WalkthroughSteps.totalSteps}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
            )

            // Next / Done button
            Button(
                onClick = onNext,
                shape = RoundedCornerShape(24.dp)
            ) {
                Text(if (isLastStep) "Done" else "Next")
                if (!isLastStep) {
                    Spacer(modifier = Modifier.width(4.dp))
                    Icon(
                        Icons.Default.ChevronRight,
                        contentDescription = "Next",
                        modifier = Modifier.size(18.dp)
                    )
                }
            }
        }

        // Skip on non-first steps
        if (currentStep > 0) {
            Spacer(modifier = Modifier.height(8.dp))
            TextButton(onClick = onSkip) {
                Text(
                    "Skip Tutorial",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f)
                )
            }
        }
    }
}

@Composable
private fun ProgressIndicator(currentStep: Int) {
    Row(
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        for (index in 0 until WalkthroughSteps.totalSteps) {
            val isActive = index <= currentStep
            val isCurrent = index == currentStep

            val width by animateDpAsState(
                targetValue = if (isCurrent) 24.dp else 8.dp,
                animationSpec = tween(250),
                label = "dotWidth$index"
            )

            val color by animateColorAsState(
                targetValue = if (isActive) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.2f),
                animationSpec = tween(250),
                label = "dotColor$index"
            )

            Box(
                modifier = Modifier
                    .height(6.dp)
                    .width(width)
                    .clip(RoundedCornerShape(3.dp))
                    .background(color)
            )
        }
    }
}

/** Map step icon name to Material icon. */
private fun stepIcon(name: String): ImageVector = when (name) {
    "dashboard" -> Icons.Default.Dashboard
    "show_chart" -> Icons.Default.ShowChart
    "search" -> Icons.Default.Search
    "star" -> Icons.Default.Star
    "link" -> Icons.Default.Link
    "chat" -> Icons.Default.Chat
    "power_settings_new" -> Icons.Default.PowerSettingsNew
    else -> Icons.Default.Info
}

/** Map tooltip position to arrow icon. */
private fun arrowIcon(position: TooltipPosition): ImageVector = when (position) {
    TooltipPosition.TOP -> Icons.Default.KeyboardArrowUp
    TooltipPosition.BOTTOM -> Icons.Default.KeyboardArrowDown
    TooltipPosition.START -> Icons.Default.KeyboardArrowLeft
    TooltipPosition.END -> Icons.Default.KeyboardArrowRight
}
