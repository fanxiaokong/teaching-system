-- 由 migrate_sqlite_to_mysql.py 自动生成

CREATE TABLE `activation_codes` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `code` VARCHAR(255) NOT NULL UNIQUE,
  `note` TEXT DEFAULT (''),
  `created_by` INT,
  `created_at` TEXT NOT NULL,
  `used_by` INT,
  `used_at` TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `app_versions` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `version_code` INT NOT NULL,
  `version_name` TEXT NOT NULL,
  `release_notes` TEXT DEFAULT (''),
  `file_name` TEXT NOT NULL DEFAULT (''),
  `file_size` BIGINT DEFAULT 0,
  `download_url` TEXT NOT NULL DEFAULT (''),
  `is_latest` INT DEFAULT 0,
  `created_at` TEXT NOT NULL,
  `platform` TEXT NOT NULL DEFAULT ('android'),
  `sha512` TEXT DEFAULT ('')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `assignments` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `course_id` INT,
  `title` TEXT NOT NULL,
  `description` TEXT DEFAULT (''),
  `deadline` TEXT DEFAULT (''),
  `is_open` INT DEFAULT 1,
  `sort_order` INT DEFAULT 0,
  `created_at` TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `attempts` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `exam_id` INT NOT NULL,
  `name` TEXT NOT NULL,
  `contact` VARCHAR(255) NOT NULL,
  `score` DOUBLE DEFAULT 0,
  `total` INT DEFAULT 0,
  `correct` INT DEFAULT 0,
  `passed` INT DEFAULT 0,
  `detail` TEXT DEFAULT ('{}'),
  `status` TEXT DEFAULT ('ongoing'),
  `switch_count` INT DEFAULT 0,
  `started_at` TEXT NOT NULL,
  `submitted_at` TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `challenge_matches` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `challenge_id` INT NOT NULL,
  `invite_code` VARCHAR(255) NOT NULL UNIQUE,
  `host_id` INT NOT NULL,
  `guest_id` INT,
  `status` TEXT DEFAULT ('waiting'),
  `host_elapsed_ms` INT DEFAULT 0,
  `guest_elapsed_ms` INT DEFAULT 0,
  `host_finished_at` TEXT,
  `guest_finished_at` TEXT,
  `created_at` TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `challenge_records` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `user_id` INT NOT NULL,
  `challenge_id` INT NOT NULL,
  `passed` INT DEFAULT 0,
  `note` TEXT DEFAULT (''),
  `file_id` INT,
  `created_at` TEXT NOT NULL,
  `elapsed_ms` INT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `challenges` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `title` TEXT NOT NULL,
  `summary` TEXT DEFAULT (''),
  `content_html` TEXT DEFAULT (''),
  `difficulty` INT DEFAULT 1,
  `deadline` TEXT DEFAULT (''),
  `is_open` INT DEFAULT 1,
  `sort_order` INT DEFAULT 0,
  `created_at` TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `course_progress` (
  `user_id` INT NOT NULL,
  `course_id` INT NOT NULL,
  `percent` INT DEFAULT 0,
  `status` TEXT DEFAULT ('learning'),
  `updated_at` TEXT,
  PRIMARY KEY (user_id, course_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `courses` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `title` TEXT NOT NULL,
  `summary` TEXT DEFAULT (''),
  `category` TEXT DEFAULT (''),
  `icon` TEXT DEFAULT (''),
  `source` TEXT DEFAULT ('editor'),
  `content_html` TEXT DEFAULT (''),
  `entry_path` TEXT DEFAULT (''),
  `sort_order` INT DEFAULT 0,
  `is_open` INT DEFAULT 1,
  `created_at` TEXT NOT NULL,
  `updated_at` TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `exams` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `title` TEXT NOT NULL,
  `description` TEXT DEFAULT (''),
  `duration_min` INT DEFAULT 30,
  `question_count` INT DEFAULT 10,
  `tag_filter` TEXT DEFAULT (''),
  `pass_score` INT DEFAULT 60,
  `is_open` INT DEFAULT 1,
  `created_at` TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `feedback` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `user_id` INT NOT NULL,
  `title` TEXT DEFAULT (''),
  `category` TEXT DEFAULT (''),
  `content` TEXT NOT NULL,
  `status` VARCHAR(255) DEFAULT 'open',
  `created_at` TEXT,
  `updated_at` TEXT,
  `replied_at` TEXT,
  `replied_by` INT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `feedback_images` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `feedback_id` INT NOT NULL,
  `stored_name` TEXT NOT NULL,
  `original_name` TEXT DEFAULT (''),
  `size` BIGINT DEFAULT 0,
  `created_at` TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `feedback_replies` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `feedback_id` INT NOT NULL,
  `user_id` INT NOT NULL,
  `is_admin` INT DEFAULT 0,
  `content` TEXT NOT NULL,
  `created_at` TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `files` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `kind` VARCHAR(255) NOT NULL DEFAULT 'resource',
  `title` TEXT NOT NULL,
  `description` TEXT DEFAULT (''),
  `stored_name` TEXT NOT NULL,
  `original_name` TEXT NOT NULL,
  `size` BIGINT DEFAULT 0,
  `category` TEXT DEFAULT (''),
  `course_id` INT,
  `challenge_id` INT,
  `owner_id` INT,
  `created_at` TEXT NOT NULL,
  `assignment_id` INT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `join_requests` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `name` TEXT NOT NULL,
  `college` TEXT NOT NULL,
  `contact` TEXT NOT NULL,
  `join_group` INT DEFAULT 0,
  `note` TEXT DEFAULT (''),
  `created_at` TEXT NOT NULL,
  `ip` TEXT DEFAULT ('')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `nav_links` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `group_name` VARCHAR(255) NOT NULL DEFAULT '常用链接',
  `title` TEXT NOT NULL,
  `url` TEXT NOT NULL,
  `icon` TEXT DEFAULT (''),
  `description` TEXT DEFAULT (''),
  `sort_order` INT DEFAULT 0,
  `created_at` TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `post_attachments` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `post_id` INT NOT NULL,
  `file_id` INT NOT NULL,
  `created_at` TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `posts` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `user_id` INT NOT NULL,
  `title` TEXT NOT NULL,
  `content` TEXT NOT NULL,
  `views` INT DEFAULT 0,
  `is_top` INT DEFAULT 0,
  `created_at` TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `practice_logs` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `name` TEXT DEFAULT (''),
  `question_id` INT,
  `user_answer` TEXT DEFAULT (''),
  `is_correct` INT DEFAULT 0,
  `created_at` TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `questions` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `qtype` TEXT NOT NULL,
  `stem` TEXT NOT NULL,
  `options` TEXT NOT NULL DEFAULT ('[]'),
  `answer` TEXT NOT NULL,
  `analysis` TEXT DEFAULT (''),
  `tag` VARCHAR(255) DEFAULT '',
  `difficulty` INT DEFAULT 1,
  `created_at` TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `registrations` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `name` TEXT NOT NULL,
  `college` TEXT NOT NULL,
  `class_name` TEXT NOT NULL,
  `contact` VARCHAR(255) NOT NULL,
  `note` TEXT DEFAULT (''),
  `created_at` VARCHAR(255) NOT NULL,
  `ip` TEXT DEFAULT ('')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `replies` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `post_id` INT NOT NULL,
  `user_id` INT NOT NULL,
  `content` TEXT NOT NULL,
  `created_at` TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `reports` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `user_id` INT NOT NULL,
  `name` TEXT NOT NULL,
  `college` TEXT NOT NULL,
  `major_class` TEXT NOT NULL,
  `joined_qq` INT DEFAULT 0,
  `status` VARCHAR(255) DEFAULT 'pending',
  `review_note` TEXT DEFAULT (''),
  `reviewed_by` INT,
  `created_at` TEXT NOT NULL,
  `reviewed_at` TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `scan_logins` (
  `token` VARCHAR(255) PRIMARY KEY,
  `user_id` INT,
  `status` TEXT DEFAULT ('pending'),
  `created_at` TEXT NOT NULL,
  `expires_at` TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `settings` (
  `k` VARCHAR(255) PRIMARY KEY,
  `v` TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `study_days` (
  `user_id` INT NOT NULL,
  `day` VARCHAR(255) NOT NULL,
  `seconds` INT DEFAULT 0,
  PRIMARY KEY (user_id, day)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `users` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `username` VARCHAR(255) NOT NULL UNIQUE,
  `phone` VARCHAR(255) NOT NULL UNIQUE,
  `password_hash` TEXT NOT NULL,
  `nickname` TEXT DEFAULT (''),
  `is_admin` INT DEFAULT 0,
  `is_active` INT DEFAULT 1,
  `created_at` TEXT NOT NULL,
  `last_login_at` TEXT,
  `quota_mb` INT DEFAULT 200,
  `student_no` TEXT DEFAULT ('')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `videos` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `course_id` INT,
  `title` TEXT NOT NULL,
  `description` TEXT DEFAULT (''),
  `stored_name` TEXT NOT NULL,
  `original_name` TEXT NOT NULL,
  `size` BIGINT DEFAULT 0,
  `sort_order` INT DEFAULT 0,
  `created_at` TEXT NOT NULL,
  `duration` TEXT DEFAULT (''),
  `subtitle` TEXT DEFAULT (''),
  `subtitle_name` TEXT DEFAULT ('')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE INDEX idx_activation_used_by ON activation_codes(used_by);
CREATE INDEX idx_app_versions_latest ON app_versions(is_latest, id);
CREATE INDEX idx_assign_course ON assignments(course_id, sort_order);
CREATE INDEX idx_att_contact ON attempts(contact);
CREATE INDEX idx_att_exam ON attempts(exam_id);
CREATE INDEX idx_fb_img_fid ON feedback_images(feedback_id);
CREATE INDEX idx_fb_reply_fid ON feedback_replies(feedback_id);
CREATE INDEX idx_feedback_status ON feedback(status);
CREATE INDEX idx_feedback_user ON feedback(user_id);
CREATE INDEX idx_files_kind ON files(kind, id);
CREATE INDEX idx_files_owner ON files(owner_id);
CREATE INDEX idx_link_group ON nav_links(group_name, sort_order);
CREATE INDEX idx_q_tag ON questions(tag);
CREATE INDEX idx_reg_contact ON registrations(contact);
CREATE INDEX idx_reg_created ON registrations(created_at);
CREATE INDEX idx_reports_status ON reports(status, id);
CREATE INDEX idx_reports_user ON reports(user_id);
CREATE INDEX idx_videos_course ON videos(course_id, sort_order);
