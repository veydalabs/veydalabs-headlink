#include <Servo.h>
#include <ctype.h>
#include <stdlib.h>
#include <string.h>

static const byte NUM_SERVOS = 8;
static const byte SERVO_PINS[NUM_SERVOS] = {3, 4, 5, 6, 7, 8, 9, 10};

// Hard safety envelope. S1..S4 are widened slightly beyond the current browser-side
// defaults so the UI can be tuned live without immediately hitting firmware clamps.
static const int SERVO_MIN_ANGLES[NUM_SERVOS] = {65, 85, 75, 85, 0, 0, 0, 0};
static const int SERVO_MAX_ANGLES[NUM_SERVOS] = {90, 125, 110, 115, 180, 180, 180, 180};
static const int SERVO_NEUTRAL_ANGLES[NUM_SERVOS] = {78, 105, 80, 110, 90, 90, 90, 90};

static const int STEP_DEGREES = 5;
static const unsigned long PRINT_INTERVAL_MS = 250;

Servo servos[NUM_SERVOS];
int angles[NUM_SERVOS] = {
  SERVO_NEUTRAL_ANGLES[0], SERVO_NEUTRAL_ANGLES[1], SERVO_NEUTRAL_ANGLES[2], SERVO_NEUTRAL_ANGLES[3],
  SERVO_NEUTRAL_ANGLES[4], SERVO_NEUTRAL_ANGLES[5], SERVO_NEUTRAL_ANGLES[6], SERVO_NEUTRAL_ANGLES[7]
};
bool servoAttached[NUM_SERVOS] = {false, false, false, false, false, false, false, false};
bool hasPose = false;

char rxBuffer[96];
byte rxIndex = 0;
unsigned long lastPrintMs = 0;

int clampServoAngle(byte index, int angle) {
  if (angle < SERVO_MIN_ANGLES[index]) return SERVO_MIN_ANGLES[index];
  if (angle > SERVO_MAX_ANGLES[index]) return SERVO_MAX_ANGLES[index];
  return angle;
}

void writeServoAngle(byte index, int targetAngle) {
  int bounded = clampServoAngle(index, targetAngle);
  if (!servoAttached[index]) {
    servos[index].attach(SERVO_PINS[index]);
    servoAttached[index] = true;
    delay(5);
  }
  angles[index] = bounded;
  servos[index].write(bounded);
  hasPose = true;
}

void printAngles() {
  if (!hasPose) {
    Serial.println("Angles: no pose sent yet");
    return;
  }

  Serial.print("Angles: ");
  for (byte i = 0; i < NUM_SERVOS; i++) {
    Serial.print("S");
    Serial.print(i + 1);
    Serial.print("=");
    Serial.print(angles[i]);
    if (i < NUM_SERVOS - 1) Serial.print("  ");
  }
  Serial.println();
}

void printHelp() {
  Serial.println("InMoov Eye Serial Servo Bridge (8-channel)");
  Serial.println("Hard safety limits:");
  Serial.println("  S1 65..90   right eye horizontal");
  Serial.println("  S2 85..125  right eye vertical");
  Serial.println("  S3 75..110  right lower lid");
  Serial.println("  S4 85..115  right upper lid");
  Serial.println("  S5 0..180   generic");
  Serial.println("  S6 0..180   generic");
  Serial.println("  S7 0..180   generic");
  Serial.println("  S8 0..180   generic");
  Serial.println("Commands:");
  Serial.println("  A a1 a2 a3 a4 a5 a6 a7 a8 -> set absolute angles");
  Serial.println("  O -> all to minimum angle");
  Serial.println("  C -> all to maximum angle");
  Serial.println("  N -> all to neutral angle");
  Serial.println("  P -> print current angles");
  Serial.println("  ? or H -> show help");
  Serial.println("Single-key manual step (5 deg):");
  Serial.println("  q/a S1 +/-    w/s S2 +/-    e/d S3 +/-    r/f S4 +/-");
  Serial.println("  t/g S5 +/-    y/h S6 +/-    u/j S7 +/-    i/k S8 +/-");
}

void applyMinPose() {
  for (byte i = 0; i < NUM_SERVOS; i++) writeServoAngle(i, SERVO_MIN_ANGLES[i]);
}

void applyMaxPose() {
  for (byte i = 0; i < NUM_SERVOS; i++) writeServoAngle(i, SERVO_MAX_ANGLES[i]);
}

void applyNeutralPose() {
  for (byte i = 0; i < NUM_SERVOS; i++) writeServoAngle(i, SERVO_NEUTRAL_ANGLES[i]);
}

void stepServo(byte index, int delta) {
  writeServoAngle(index, angles[index] + delta);
  printAngles();
}

void handleSingleKey(char c) {
  char key = (char)tolower((unsigned char)c);
  switch (key) {
    case 'q': stepServo(0, +STEP_DEGREES); break;
    case 'a': stepServo(0, -STEP_DEGREES); break;
    case 'w': stepServo(1, +STEP_DEGREES); break;
    case 's': stepServo(1, -STEP_DEGREES); break;
    case 'e': stepServo(2, +STEP_DEGREES); break;
    case 'd': stepServo(2, -STEP_DEGREES); break;
    case 'r': stepServo(3, +STEP_DEGREES); break;
    case 'f': stepServo(3, -STEP_DEGREES); break;
    case 't': stepServo(4, +STEP_DEGREES); break;
    case 'g': stepServo(4, -STEP_DEGREES); break;
    case 'y': stepServo(5, +STEP_DEGREES); break;
    case 'h': stepServo(5, -STEP_DEGREES); break;
    case 'u': stepServo(6, +STEP_DEGREES); break;
    case 'j': stepServo(6, -STEP_DEGREES); break;
    case 'i': stepServo(7, +STEP_DEGREES); break;
    case 'k': stepServo(7, -STEP_DEGREES); break;
    default:
      break;
  }
}

void handleLine(char* line) {
  if (line[0] == '\0') return;

  if (line[1] == '\0') {
    char rawKey = line[0];
    char key = (char)toupper((unsigned char)rawKey);
    if (rawKey == '?' || rawKey == 'H') {
      printHelp();
      return;
    }
    if (key == 'O') {
      applyMinPose();
      printAngles();
      return;
    }
    if (key == 'C') {
      applyMaxPose();
      printAngles();
      return;
    }
    if (key == 'N') {
      applyNeutralPose();
      printAngles();
      return;
    }
    if (key == 'P') {
      printAngles();
      return;
    }
    handleSingleKey(rawKey);
    return;
  }

  if (toupper((unsigned char)line[0]) != 'A') {
    Serial.print("Unknown command: ");
    Serial.println(line);
    return;
  }

  int values[NUM_SERVOS];
  byte parsed = 0;
  char* token = strtok(line + 1, " ,\t");
  while (token != NULL && parsed < NUM_SERVOS) {
    values[parsed++] = atoi(token);
    token = strtok(NULL, " ,\t");
  }

  if (parsed != NUM_SERVOS) {
    Serial.println("ERR expected 8 angles");
    return;
  }

  for (byte i = 0; i < NUM_SERVOS; i++) writeServoAngle(i, values[i]);

  unsigned long now = millis();
  if (now - lastPrintMs >= PRINT_INTERVAL_MS) {
    printAngles();
    lastPrintMs = now;
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);
  printHelp();
  Serial.println("Servos idle until first command.");
  printAngles();
}

void loop() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();

    if (c == '\r') continue;

    if (c == '\n') {
      rxBuffer[rxIndex] = '\0';
      handleLine(rxBuffer);
      rxIndex = 0;
      continue;
    }

    if (rxIndex < sizeof(rxBuffer) - 1) {
      rxBuffer[rxIndex++] = c;
    } else {
      rxIndex = 0;
      Serial.println("ERR command too long");
    }
  }
}
